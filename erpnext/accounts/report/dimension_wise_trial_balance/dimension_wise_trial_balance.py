# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe, erpnext
from frappe import _
from frappe.utils import flt, getdate, formatdate, cstr
from erpnext.accounts.report.financial_statements import filter_accounts, set_gl_entries_by_account, \
	filter_out_zero_value_rows
from erpnext.accounts.report.trial_balance.trial_balance import validate_filters, get_rootwise_opening_balances
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions, \
	get_dimension_with_children


def execute(filters=None):
	validate_filters(filters)
	dimension_field = get_dimension_field(filters.get("based_on"))

	data = get_data(filters, dimension_field)
	columns = get_columns(data.get('dimension_values', []), data.get('dimension_labels', []))
	return columns, data.get('report_data', [])


def get_dimension_field(based_on_value):
	"""Get the field name from the based on value dynamically"""
	if not based_on_value:
		return None

	if based_on_value == "Cost Center":
		return "cost_center"

	accounting_dimensions = get_accounting_dimensions(as_list=False)
	for dimension in accounting_dimensions:
		if dimension.document_type == based_on_value:
			return dimension.fieldname

	return None


def get_data(filters, dimension_field):
	"""Main data processing function"""
	accounts = frappe.db.sql("""SELECT name, account_number, parent_account, account_name, root_type, report_type, lft, rgt
        FROM `tabAccount`
		WHERE company = %s
		ORDER BY lft
	""", filters.company, as_dict=True)

	if not accounts:
		return {"report_data": [], "dimension_values": [], "dimension_labels": {}}

	company_currency = erpnext.get_company_currency(filters.company)
	accounts, accounts_by_name, parent_children_map = filter_accounts(accounts)

	min_lft, max_rgt = frappe.db.sql("""
		select min(lft), max(rgt)
		from `tabAccount`
		where company=%s
	""", (filters.company,))[0]

	gl_entries_by_account = {}

	opening_balances = get_opening_balances(filters, dimension_field)

	# add filter inside list so that the query in financial_statements.py doesn't break
	if filters.project:
		filters.project = [filters.project]

	set_gl_entries_by_account(filters.company, filters.from_date, filters.to_date,
		min_lft, max_rgt, filters, gl_entries_by_account,
		ignore_closing_entries=not flt(filters.with_period_closing_entry),dimension_field=dimension_field)

	dimension_values, dimension_labels = get_dimension_values(opening_balances, gl_entries_by_account, dimension_field)

	total_row = calculate_values(accounts, gl_entries_by_account, opening_balances, filters,
		company_currency, dimension_values, dimension_field)

	accumulate_values_into_parents(accounts, accounts_by_name, dimension_values)

	data = prepare_data(accounts, filters, total_row, company_currency, dimension_values)
	data = filter_out_zero_value_rows(data, parent_children_map, show_zero_values=filters.get("show_zero_values"))

	set_zero_for_group_accounts(data, parent_children_map, dimension_values)

	return {
		"report_data": data,
		"dimension_values": dimension_values,
		"dimension_labels": dimension_labels
	}


def get_opening_balances(filters, dimension_field):
	"""Get opening balances for both Balance Sheet and P&L accounts"""
	balance_sheet_opening = get_rootwise_opening_balances(filters, "Balance Sheet", dimension_field)
	pl_opening = get_rootwise_opening_balances(filters, "Profit and Loss", dimension_field)

	balance_sheet_opening.update(pl_opening)
	return balance_sheet_opening


def get_dimension_values(opening_balances, gl_entries_by_account, dimension_field):
	"""Extract unique dimension values and labels from data"""
	dimension_values = set()
	dimension_labels = {}

	# Get dimension values from opening balances
	for account_name, dimension_data in opening_balances.items():
		for dim_value, entry_data in dimension_data.items():
			if dim_value:
				dimension_values.add(dim_value)
				dimension_labels[dim_value] = entry_data.get('dimension_label', dim_value)

	# Get dimension values from GL entries
	for account, gl_entries in gl_entries_by_account.items():
		for entry in gl_entries:
			dim_value = entry.get(dimension_field) if dimension_field else None
			if dim_value:
				dimension_values.add(dim_value)
				if dim_value not in dimension_labels:
					dimension_labels[dim_value] = dim_value

	return sorted(dimension_values), dimension_labels


def calculate_values(accounts, gl_entries_by_account, opening_balances, filters, company_currency, dimension_values,
		dimension_field):
	"""Calculate opening, movement, and closing values for each account and dimension"""
	init = {}
	for dim in dimension_values:
		init[f"opening_{dim}"] = 0.0
		init[f"movement_{dim}"] = 0.0
		init[f"closing_{dim}"] = 0.0

	total_row = {
		"account": "'" + _("Total") + "'",
		"account_name": "'" + _("Total") + "'",
		"warn_if_negative": True,
		"parent_account": None,
		"indent": 0,
		"has_value": True,
		"currency": company_currency
	}

	for dim in dimension_values:
		total_row[f"opening_{dim}"] = 0.0
		total_row[f"movement_{dim}"] = 0.0
		total_row[f"closing_{dim}"] = 0.0

	for account in accounts:
		account.update(init.copy())

		account_opening = opening_balances.get(account.name, {})

		for dim_value, entry_data in account_opening.items():
			opening_debit = entry_data.get('opening_debit', 0) or 0
			opening_credit = entry_data.get('opening_credit', 0) or 0

			if dim_value and dim_value in dimension_values:
				account[f"opening_{dim_value}"] = opening_debit - opening_credit

		for entry in gl_entries_by_account.get(account.name, []):
			if cstr(entry.is_opening) == "Yes":
				continue

			dim_value = entry.get(dimension_field) if dimension_field else None
			debit = flt(entry.debit)
			credit = flt(entry.credit)

			if dim_value and dim_value in dimension_values:
				account[f"movement_{dim_value}"] += debit - credit

		# Calculate closing balances and add to totals
		for dim in dimension_values:
			account[f"closing_{dim}"] = account[f"opening_{dim}"] + account[f"movement_{dim}"]

			# Add to totals
			total_row[f"opening_{dim}"] += account[f"opening_{dim}"]
			total_row[f"movement_{dim}"] += account[f"movement_{dim}"]
			total_row[f"closing_{dim}"] += account[f"closing_{dim}"]

	return total_row


def accumulate_values_into_parents(accounts, accounts_by_name, dimension_values):
	"""Accumulate child values into parent accounts"""
	for account in reversed(accounts):
		if account.parent_account and account.parent_account in accounts_by_name:
			parent = accounts_by_name[account.parent_account]
			for dim in dimension_values:
				for field_type in ["opening", "movement", "closing"]:
					key = f"{field_type}_{dim}"
					parent[key] = parent.get(key, 0) + account.get(key, 0)


def prepare_data(accounts, filters, total_row, company_currency, dimension_values):
	"""Prepare final data for report"""
	data = []

	for account in accounts:
		has_value = False
		row = {
			"account": account.name,
			"parent_account": account.parent_account,
			"indent": account.indent,
			"from_date": filters.from_date,
			"to_date": filters.to_date,
			"currency": company_currency,
			"account_name": ('{0} - {1}'.format(account.account_number, account.account_name)
				if account.account_number else account.account_name)
		}

		# Add dimension values
		for dim in dimension_values:
			for field_type in ["opening", "movement", "closing"]:
				key = f"{field_type}_{dim}"
				row[key] = flt(account.get(key, 0.0), 3)
				if abs(row[key]) >= 0.005:
					has_value = True

		row["has_value"] = has_value
		data.append(row)

	for dim in dimension_values:
		for field_type in ["opening", "movement", "closing"]:
			key = f"{field_type}_{dim}"
			total_row[key] = flt(total_row.get(key, 0.0), 3)

	data.extend([{}, total_row])
	return data


def set_zero_for_group_accounts(data, parent_children_map, dimension_values):
	"""Hide parent account totals for grouped reports while keeping structure visible"""
	for row in data:
		if row.get('account') and parent_children_map.get(row['account']):
			for dim in dimension_values:
				for field_type in ["opening", "movement", "closing"]:
					key = f"{field_type}_{dim}"
					if key in row:
						del row[key]


def get_columns(dimension_values=None, dimension_labels=None):
	"""Generate report columns with dimension-wise grouping"""
	if not dimension_values:
		dimension_values = []
	if not dimension_labels:
		dimension_labels = {}

	columns = [
		{
			"fieldname": "account",
			"label": _("Account"),
			"fieldtype": "Link",
			"options": "Account",
			"width": 300
		},
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"hidden": 1
		}
	]

	for column_type in ["opening", "movement", "closing"]:
		for dim_value in dimension_values:
			display_label = dimension_labels.get(dim_value, dim_value)
			columns.append({
				"fieldname": f"{column_type}_{dim_value}",
				"label": f"{column_type.title()} {display_label}",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120
			})

	return columns
