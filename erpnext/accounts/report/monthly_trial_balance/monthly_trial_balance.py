# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe, erpnext
from frappe import _, unscrub
from frappe.utils import flt, getdate, cstr
from erpnext.accounts.report.financial_statements \
	import filter_accounts, set_gl_entries_by_account, filter_out_zero_value_rows
from erpnext.accounts.report.trial_balance.trial_balance import validate_filters, get_rootwise_opening_balances, \
	get_dimension_dict_from_key, get_dimension_key, dimension_sorter, get_dimension_dict, get_dimension_column_details
from erpnext.accounts.report.financial_statements import get_period_list
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions, \
	get_dimension_with_children, get_all_dimension_fields

def execute(filters=None):
	validate_filters(filters)

	period_list = get_period_list(filters.fiscal_year, filters.fiscal_year, "Monthly", False, filters.company)

	data = get_data(filters, period_list)
	columns = get_columns(filters, period_list)
	return columns, data


def get_data(filters, period_list):
	accounts = frappe.db.sql("""
		select name, account_number, parent_account, account_name, root_type, report_type, lft, rgt, is_group
		from `tabAccount`
		where company=%s order by lft
	""", filters.company, as_dict=True)

	if not accounts:
		return None

	company_currency = erpnext.get_company_currency(filters.company)

	accounts, accounts_by_name, parent_children_map = filter_accounts(accounts)

	min_lft, max_rgt = frappe.db.sql("""
		select min(lft), max(rgt)
		from `tabAccount`
		where company=%s
	""", (filters.company,))[0]

	opening_balances = get_opening_balances(filters, dimension_fields=filters.dimension_fields)

	# add filter inside list so that the query in financial_statements.py doesn't break
	if filters.project:
		filters.project = [filters.project]

	gl_entries_by_account = {}
	set_gl_entries_by_account(filters.company, filters.from_date, filters.to_date,
		min_lft, max_rgt, filters, gl_entries_by_account,
		ignore_closing_entries=not flt(filters.with_period_closing_entry),
		dimension_fields=filters.dimension_fields,
	)

	total_rows = calculate_values(accounts, gl_entries_by_account, opening_balances, filters, company_currency, period_list,
		dimension_fields=filters.dimension_fields)
	accumulate_values_into_parents(accounts, accounts_by_name, period_list)

	data = prepare_data(accounts, filters, total_rows, parent_children_map, company_currency, period_list, dimension_fields=filters.dimension_fields)
	data = filter_out_zero_value_rows(data, parent_children_map, show_zero_values=filters.get("show_zero_values"))

	set_zero_for_group_accounts(data, parent_children_map, period_list)

	return data


def get_opening_balances(filters, dimension_fields=None):
	balance_sheet_opening = get_rootwise_opening_balances(filters, "Balance Sheet", dimension_fields)
	pl_opening = get_rootwise_opening_balances(filters, "Profit and Loss", dimension_fields)

	balance_sheet_opening.update(pl_opening)
	return balance_sheet_opening


def calculate_values(accounts, gl_entries_by_account, opening_balances, filters, company_currency, period_list, dimension_fields=None):
	init = {
		"opening_balance": 0.0,
		"debit": 0.0,
		"credit": 0.0,
		"closing_balance": 0.0,
	}
	for period in period_list:
		init[period.key] = 0

	total_row_init = {
		"account_display": _("Total"),
		"account_name": _("Total"),
		"warn_if_negative": True,
		"opening_balance": 0.0,
		"debit": 0.0,
		"credit": 0.0,
		"closing_balance": 0.0,
		"parent_account": None,
		"indent": 0,
		"has_value": True,
		"currency": company_currency
	}
	for period in period_list:
		total_row_init[period.key] = 0

	dimension_totals = {}
	grand_total_row = total_row_init.copy()

	def get_dimension_object(account_obj, dimension_key):
		if dimension_key not in account_obj.dimensions:
			dimension_object = account_obj.dimensions[dimension_key] = init.copy()
			dimension_dict = get_dimension_dict_from_key(dimension_key, dimension_fields)
			dimension_object.update(dimension_dict)

		return account_obj.dimensions[dimension_key]

	for d in accounts:
		d.update(init.copy())
		d["dimensions"] = {}

		# add opening
		account_opening = opening_balances.get(d.name, frappe._dict())
		d["opening_balance"] = account_opening.get("opening_debit", 0) - account_opening.get("opening_credit", 0)

		for dimension_key, dimension_opening in account_opening.get("dimensions", {}).items():
			dim = get_dimension_object(d, dimension_key)
			dim["opening_balance"] = flt(dimension_opening.get("opening_debit")) - flt(dimension_opening.get("opening_credit"))

		# add movement
		for entry in gl_entries_by_account.get(d.name, []):
			if cstr(entry.is_opening) == "Yes":
				continue

			d["debit"] += flt(entry.debit)
			d["credit"] += flt(entry.credit)

			for period in period_list:
				if period.from_date <= getdate(entry.posting_date) <= period.to_date:
					d[period.key] += flt(entry.debit) - flt(entry.credit)

			if dimension_fields:
				dimension_key = get_dimension_key(entry, dimension_fields)
				dim = get_dimension_object(d, dimension_key)
				dim["debit"] += flt(entry.debit)
				dim["credit"] += flt(entry.credit)

				for period in period_list:
					if period.from_date <= getdate(entry.posting_date) <= period.to_date:
						dim[period.key] += flt(entry.debit) - flt(entry.credit)

		# calculate closing
		d["closing_balance"] = d["opening_balance"] + d["debit"] - d["credit"]

		for dimension_key, dim in d.get("dimensions", {}).items():
			dim["closing_balance"] = dim["opening_balance"] + dim["debit"] - dim["credit"]

		# accumulate total rows
		if dimension_fields:
			for dimension_key, dim in d.get("dimensions", {}).items():
				dimension_total_row = dimension_totals.get(dimension_key)
				if not dimension_total_row:
					dimension_total_row = dimension_totals[dimension_key] = total_row_init.copy()
					dimension_total_row["account_name"] = _("Dimension Total")
					dimension_total_row["account_display"] = _("Dimension Total")
					dimension_dict = get_dimension_dict_from_key(dimension_key, dimension_fields)
					dimension_total_row.update(dimension_dict)

				for field in get_value_fields(period_list):
					dimension_total_row[field] += dim[field]
					grand_total_row[field] += dim[field]
		else:
			for field in get_value_fields(period_list):
				grand_total_row[field] += d[field]

	if dimension_fields:
		total_rows = sorted(dimension_totals.values(), key=lambda d: dimension_sorter(d, dimension_fields)) + [{}, grand_total_row]
	else:
		total_rows = [grand_total_row]

	return total_rows


def accumulate_values_into_parents(accounts, accounts_by_name, period_list):
	for d in reversed(accounts):
		if d.parent_account:
			for key in get_value_fields(period_list):
				accounts_by_name[d.parent_account][key] += d[key]


def set_zero_for_group_accounts(data, parent_children_map, period_list):
	for d in data:
		if d.get('account') and parent_children_map.get(d['account']):
			for key in get_value_fields(period_list):
				del d[key]


def prepare_data(accounts, filters, total_rows, parent_children_map, company_currency, period_list, dimension_fields=None):
	data = []

	for acc in accounts:
		if dimension_fields and not acc.is_group:
			sources = acc.dimensions.values() or [acc]
		else:
			sources = [acc]

		account_rows = []

		for d in sources:
			has_value = False
			row = {
				"account": acc.name,
				"account_number": acc.account_number,
				"account_name": acc.account_name,
				"account_display": f"{acc.account_number} - {acc.account_name}" if acc.account_number else acc.account_name,
				"parent_account": acc.parent_account,
				"is_group": acc.is_group,
				"from_date": filters.from_date,
				"to_date": filters.to_date,
				"currency": company_currency,
			}

			if dimension_fields:
				dimension_dict = get_dimension_dict(d, dimension_fields)
				row.update(dimension_dict)

			if filters.show_tree:
				row["indent"] = getattr(d, 'indent', acc.indent)

			for key in get_value_fields(period_list):
				row[key] = flt(d.get(key, 0.0), 3)

				if abs(row[key]) >= 0.005:
					# ignore zero values
					has_value = True

			row["has_value"] = has_value
			if not acc.is_group or filters.show_tree:
				account_rows.append(row)

		if dimension_fields:
			account_rows = sorted(account_rows, key=lambda d: dimension_sorter(d, dimension_fields))

		data += account_rows

	data.append({})
	data += total_rows

	return data


def get_value_fields(period_list):
	value_fields = ["opening_balance", "debit", "credit", "closing_balance"]
	for period in period_list:
		value_fields.append(period.key)

	return value_fields


def get_columns(filters, period_list):
	if filters.show_tree:
		columns = [
			{
				"fieldname": "account_display",
				"label": _("Account"),
				"fieldtype": "Data",
				"width": 300,
			},
		]
	else:
		columns = [
			{
				"fieldname": "account_number",
				"label": _("Account Number"),
				"fieldtype": "Data",
				"width": 108,
			},
			{
				"fieldname": "account_name",
				"label": _("Account Name"),
				"fieldtype": "Data",
				"width": 200,
			},
		]

	for f in filters.dimension_fields:
		dimension_details = get_dimension_column_details(f)
		columns.append({
			"fieldname": f,
			"label": dimension_details.label,
			"fieldtype": "Link" if dimension_details.document_type else "Data",
			"options": dimension_details.document_type,
			"width": 150,
		})

	columns += [
		{
			"fieldname": "opening_balance",
			"label": _("Opening Balance"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
	]

	for period in period_list:
		columns.append({
			"fieldname": period.key,
			"label": period.label,
			"fieldtype": "Currency",
			"options": "currency",
			"width": 110
		})

	columns += [
		{
			"fieldname": "closing_balance",
			"label": _("Closing Balance"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"hidden": 1
		},
	]

	return columns
