# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe, erpnext
from frappe import _
from frappe.utils import flt, getdate, formatdate, cstr
from erpnext.accounts.report.financial_statements \
	import filter_accounts, set_gl_entries_by_account, filter_out_zero_value_rows
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions, get_dimension_with_children
from collections import defaultdict

value_fields = ("opening_debit", "opening_credit", "debit", "credit", "closing_debit", "closing_credit")


def execute(filters=None):
	validate_filters(filters)
	dimension_field = get_dimension_field(filters.get("based_on"))

	data = get_data(filters, dimension_field=dimension_field)
	columns = get_columns(filters, dimension_field=dimension_field)
	return columns, data


def validate_filters(filters):
	if not filters.fiscal_year:
		frappe.throw(_("Fiscal Year {0} is required").format(filters.fiscal_year))

	fiscal_year = frappe.db.get_value("Fiscal Year", filters.fiscal_year, ["year_start_date", "year_end_date"], as_dict=True)
	if not fiscal_year:
		frappe.throw(_("Fiscal Year {0} does not exist").format(filters.fiscal_year))
	else:
		filters.year_start_date = getdate(fiscal_year.year_start_date)
		filters.year_end_date = getdate(fiscal_year.year_end_date)

	if not filters.from_date:
		filters.from_date = filters.year_start_date

	if not filters.to_date:
		filters.to_date = filters.year_end_date

	filters.from_date = getdate(filters.from_date)
	filters.to_date = getdate(filters.to_date)

	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be greater than To Date"))

	if (filters.from_date < filters.year_start_date) or (filters.from_date > filters.year_end_date):
		frappe.msgprint(_("From Date should be within the Fiscal Year. Assuming From Date = {0}")\
			.format(formatdate(filters.year_start_date)))

		filters.from_date = filters.year_start_date

	if (filters.to_date < filters.year_start_date) or (filters.to_date > filters.year_end_date):
		frappe.msgprint(_("To Date should be within the Fiscal Year. Assuming To Date = {0}")\
			.format(formatdate(filters.year_end_date)))
		filters.to_date = filters.year_end_date


def get_dimension_field(based_on_value):
	if not based_on_value:
		return None

	if based_on_value == "Cost Center":
		return "cost_center"

	accounting_dimensions = get_accounting_dimensions(as_list=False)
	for dimension in accounting_dimensions:
		if dimension.document_type == based_on_value:
			return dimension.fieldname

	return None


def get_dimension_label(dimension_field):
	if dimension_field == "cost_center":
		return "Cost Center"

	accounting_dimensions = get_accounting_dimensions(as_list=False)
	for dimension in accounting_dimensions:
		if dimension.fieldname == dimension_field:
			return dimension.document_type

	return dimension_field.replace("_", " ").title()


def get_data(filters, dimension_field=None):
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

	gl_entries_by_account = {}

	opening_balances = get_opening_balances(filters, dimension_field)

	# add filter inside list so that the query in financial_statements.py doesn't break
	if filters.project:
		filters.project = [filters.project]

	set_gl_entries_by_account(filters.company, filters.from_date, filters.to_date,
		min_lft, max_rgt, filters, gl_entries_by_account,
		ignore_closing_entries=not flt(filters.with_period_closing_entry),
		dimension_field=dimension_field)

	account_data, dimension_values, total_rows = calculate_values(
		accounts, gl_entries_by_account, opening_balances, dimension_field, company_currency)

	accumulate_values_into_parents(account_data, dimension_values, accounts_by_name, accounts)

	data = prepare_data(accounts, filters, account_data, dimension_values, total_rows,
		parent_children_map, company_currency, dimension_field)

	data = filter_out_zero_value_rows(data, parent_children_map, show_zero_values=filters.get("show_zero_values"))

	set_zero_for_group_accounts(data, parent_children_map)

	return data


def get_opening_balances(filters, dimension_field=None):
	balance_sheet_opening = get_rootwise_opening_balances(filters, "Balance Sheet", dimension_field)
	pl_opening = get_rootwise_opening_balances(filters, "Profit and Loss", dimension_field)

	balance_sheet_opening.update(pl_opening)
	return balance_sheet_opening


def get_rootwise_opening_balances(filters, report_type, dimension_field=None):
	additional_conditions = []
	if not filters.show_unclosed_fy_pl_balances and report_type == "Profit and Loss":
		additional_conditions.append("posting_date >= %(year_start_date)s")

	if not flt(filters.with_period_closing_entry):
		additional_conditions.append("voucher_type != 'Period Closing Voucher'")

	if filters.cost_center:
		lft, rgt = frappe.db.get_value('Cost Center', filters.cost_center, ['lft', 'rgt'])
		additional_conditions.append("""cost_center in (select name from `tabCost Center`
			where lft >= {0} and rgt <= {1})""".format(lft, rgt))

	if filters.project:
		additional_conditions.append("project = %(project)s")

	if filters.finance_book:
		fb_conditions = "finance_book = %(finance_book)s"
		if filters.include_default_book_entries:
			fb_conditions = "(finance_book in (%(finance_book)s, %(company_fb)s, '') OR finance_book IS NULL)"

		additional_conditions.append(fb_conditions)

	accounting_dimensions = get_accounting_dimensions(as_list=False)

	query_filters = {
		"company": filters.company,
		"from_date": filters.from_date,
		"report_type": report_type,
		"year_start_date": filters.year_start_date,
		"project": filters.project,
		"finance_book": filters.finance_book,
		"company_fb": frappe.db.get_value("Company", filters.company, 'default_finance_book')
	}

	if accounting_dimensions:
		for dimension in accounting_dimensions:
			if filters.get(dimension.fieldname):
				if frappe.get_cached_value('DocType', dimension.document_type, 'is_tree'):
					filters[dimension.fieldname] = get_dimension_with_children(dimension.document_type,
						filters.get(dimension.fieldname))
					additional_conditions.append("{0} in %({0})s".format(dimension.fieldname))
				else:
					additional_conditions.append("{0} in (%({0})s)".format(dimension.fieldname))

				query_filters.update({
					dimension.fieldname: filters.get(dimension.fieldname)
				})

	hooks = frappe.get_hooks('set_gl_conditions')
	for method in hooks:
		frappe.get_attr(method)(filters, additional_conditions, alias="gle")

	additional_conditions = " and {0}".format(" and ".join(additional_conditions)) if additional_conditions else ""

	select_fields = ["gle.account", "sum(gle.debit) as opening_debit", "sum(gle.credit) as opening_credit"]
	if dimension_field:
		select_fields.append(f"gle.{dimension_field}")
		if dimension_field == 'cost_center':
			select_fields.append("cc.cost_center_name as dimension_label")
		else:
			select_fields.append(f"gle.{dimension_field} as dimension_label")

	select_fields_str = ", ".join(select_fields)

	cost_center_join = ""
	if dimension_field == 'cost_center':
		cost_center_join = "LEFT JOIN `tabCost Center` cc ON gle.cost_center = cc.name"

	group_by = "gle.account"
	if dimension_field:
		group_by = f"gle.account, gle.{dimension_field}"

	gle = frappe.db.sql(f"""
		select {select_fields_str}
		from `tabGL Entry` gle
		{cost_center_join}
		where gle.company = %(company)s
			{additional_conditions}
			and (gle.posting_date < %(from_date)s or gle.is_opening = 'Yes')
			and account in (select acc.name from `tabAccount` acc where acc.report_type = %(report_type)s)
		group by {group_by}
	""", query_filters, as_dict=True)

	opening = frappe._dict()
	for d in gle:
		if dimension_field:
			opening.setdefault(d.account, {}).setdefault(cstr(d.get(dimension_field)), d)
		else:
			opening.setdefault(d.account, d)

	if not dimension_field:
		hooks = frappe.get_hooks('get_opening_account_balances')
		for method in hooks:
			opening_balances = frappe.get_attr(method)(filters)
			if opening_balances is None:
				continue

			for account, opening_entry in opening_balances.items():
				opening_data = opening.setdefault(account, frappe._dict({
					'account': account, 'opening_debit': 0, 'opening_credit': 0
				}))

				if opening_entry.opening_balance >= 0:
					opening_data['opening_debit'] += opening_entry.opening_balance
				else:
					opening_data['opening_credit'] += -1 * opening_entry.opening_balance

	return opening


def calculate_values(accounts, gl_entries_by_account, opening_balances, dimension_field, company_currency):
	dimension_values = set()

	if dimension_field:
		account_data = defaultdict(lambda: defaultdict(lambda: {
			"opening_debit": 0.0, "opening_credit": 0.0, "debit": 0.0,
			"credit": 0.0, "closing_debit": 0.0, "closing_credit": 0.0
		}))
	else:
		account_data = {}
		dimension_values.add(None)

	for account_name, opening_data in opening_balances.items():
		if dimension_field and isinstance(opening_data, dict):
			for dim_value, data in opening_data.items():
				clean_dim_value = dim_value or _("Empty")
				dimension_values.add(clean_dim_value)
				account_data[account_name][clean_dim_value]["opening_debit"] = data.get("opening_debit", 0)
				account_data[account_name][clean_dim_value]["opening_credit"] = data.get("opening_credit", 0)
		else:
			if dimension_field:
				clean_dim_value = _("Empty")
				dimension_values.add(clean_dim_value)
				account_data[account_name][clean_dim_value]["opening_debit"] = opening_data.get("opening_debit", 0)
				account_data[account_name][clean_dim_value]["opening_credit"] = opening_data.get("opening_credit", 0)
			else:
				account_data[account_name] = {
					"opening_debit": opening_data.get("opening_debit", 0),
					"opening_credit": opening_data.get("opening_credit", 0),
					"debit": 0.0, "credit": 0.0, "closing_debit": 0.0, "closing_credit": 0.0
				}

	for account_name, gl_entries in gl_entries_by_account.items():
		for entry in gl_entries:
			if cstr(entry.is_opening) == "Yes":
				continue

			if dimension_field:
				dim_value = entry.get(dimension_field) or _("Empty")
				dimension_values.add(dim_value)
				account_data[account_name][dim_value]["debit"] += flt(entry.debit)
				account_data[account_name][dim_value]["credit"] += flt(entry.credit)
			else:
				if account_name not in account_data:
					account_data[account_name] = {
						"opening_debit": 0.0, "opening_credit": 0.0,
						"debit": 0.0, "credit": 0.0, "closing_debit": 0.0, "closing_credit": 0.0
					}
				account_data[account_name]["debit"] += flt(entry.debit)
				account_data[account_name]["credit"] += flt(entry.credit)

	for account in accounts:
		if dimension_field:
			for dim_value in dimension_values:
				account_data[account.name][dim_value]["root_type"] = account.root_type
		else:
			if account.name not in account_data:
				account_data[account.name] = {
					"opening_debit": 0.0, "opening_credit": 0.0,
					"debit": 0.0, "credit": 0.0, "closing_debit": 0.0, "closing_credit": 0.0
				}
			account_data[account.name]["root_type"] = account.root_type

	if dimension_field:
		for account_name, account_dims in account_data.items():
			for dim_value, data in account_dims.items():
				data["closing_debit"] = data["opening_debit"] + data["debit"]
				data["closing_credit"] = data["opening_credit"] + data["credit"]
				prepare_opening_closing(data)
	else:
		for account_name, data in account_data.items():
			data["closing_debit"] = data["opening_debit"] + data["debit"]
			data["closing_credit"] = data["opening_credit"] + data["credit"]
			prepare_opening_closing(data)

	total_rows = create_total_rows(dimension_values, company_currency, dimension_field)

	return (dict(account_data) if dimension_field else account_data), sorted(dimension_values), total_rows


def create_total_rows(dimension_values, company_currency, dimension_field):
	total_rows = {}

	for dim_value in dimension_values:
		total_row = {
			"account_name": _("Total"),
			"account_display": _("Total"),
			"warn_if_negative": True,
			"opening_debit": 0.0,
			"opening_credit": 0.0,
			"debit": 0.0,
			"credit": 0.0,
			"closing_debit": 0.0,
			"closing_credit": 0.0,
			"parent_account": None,
			"has_value": True,
			"currency": company_currency
		}

		if dimension_field and dim_value is not None:
			total_row["dimension_value"] = dim_value

		total_rows[dim_value] = total_row

	return total_rows


def accumulate_values_into_parents(account_data, dimension_values, accounts_by_name, accounts):
	for account in reversed(accounts):
		if account.parent_account and account.parent_account in accounts_by_name:
			if len(dimension_values) > 1 or (len(dimension_values) == 1 and None not in dimension_values):
				# Dimension case
				for dim_value in dimension_values:
					child_data = account_data.get(account.name, {}).get(dim_value, {})
					parent_data = account_data.setdefault(account.parent_account, {}).setdefault(dim_value, {
						"opening_debit": 0.0, "opening_credit": 0.0, "debit": 0.0,
						"credit": 0.0, "closing_debit": 0.0, "closing_credit": 0.0
					})

					if "root_type" not in parent_data:
						parent_data["root_type"] = accounts_by_name[account.parent_account].root_type

					for field in value_fields:
						parent_data[field] += child_data.get(field, 0)
			else:
				child_data = account_data.get(account.name, {})
				parent_data = account_data.setdefault(account.parent_account, {
					"opening_debit": 0.0, "opening_credit": 0.0, "debit": 0.0,
					"credit": 0.0, "closing_debit": 0.0, "closing_credit": 0.0
				})

				if "root_type" not in parent_data:
					parent_data["root_type"] = accounts_by_name[account.parent_account].root_type

				for field in value_fields:
					parent_data[field] += child_data.get(field, 0)


def set_zero_for_group_accounts(data, parent_children_map):
	for d in data:
		if d.get('account') and parent_children_map.get(d['account']):
			for key in value_fields:
				del d[key]


def prepare_data(accounts, filters, account_data, dimension_values, total_rows, parent_children_map, company_currency, dimension_field):
	data = []
	is_dimension_case = dimension_field and len(dimension_values) > 1 or (len(dimension_values) == 1 and None not in dimension_values)

	for account in accounts:
		is_group_account = parent_children_map.get(account.name)

		if is_dimension_case:
			if is_group_account:
				aggregated_data = {
					"opening_debit": 0.0, "opening_credit": 0.0, "debit": 0.0,
					"credit": 0.0, "closing_debit": 0.0, "closing_credit": 0.0,
					"root_type": account.root_type
				}

				account_dims = account_data.get(account.name, {})
				for dim_value in dimension_values:
					dimension_data = account_dims.get(dim_value, {})
					for field in value_fields:
						aggregated_data[field] += dimension_data.get(field, 0)

				prepare_opening_closing(aggregated_data)

				if has_account_value(aggregated_data) or filters.get("show_zero_values"):
					row = build_account_row(account, filters, company_currency)
					row["has_value"] = has_account_value(aggregated_data)

					for field in value_fields:
						row[field] = flt(aggregated_data.get(field, 0.0), 3)

					if not account.is_group or filters.show_tree:
						data.append(row)
			else:
				for dim_value in dimension_values:
					dimension_data = account_data.get(account.name, {}).get(dim_value, {})

					if has_account_value(dimension_data) or filters.get("show_zero_values"):
						row = build_account_row(account, filters, company_currency, dim_value)
						row["has_value"] = has_account_value(dimension_data)

						for field in value_fields:
							row[field] = flt(dimension_data.get(field, 0.0), 3)
							total_rows[dim_value][field] += row[field]

						if not account.is_group or filters.show_tree:
							data.append(row)
		else:
			account_values = account_data.get(account.name, {})

			if is_group_account and account_values:
				prepare_opening_closing(account_values)

			if has_account_value(account_values) or filters.get("show_zero_values"):
				row = build_account_row(account, filters, company_currency)
				row["has_value"] = has_account_value(account_values)

				for field in value_fields:
					row[field] = flt(account_values.get(field, 0.0), 3)
					if (not account.is_group or filters.show_tree) and not is_group_account:
						total_rows[None][field] += row[field]

				if not account.is_group or filters.show_tree:
					data.append(row)

	data.append({})

	if is_dimension_case:
		for dim_value in dimension_values:
			if filters.show_tree:
				total_rows[dim_value]["indent"] = 0
			data.append(total_rows[dim_value])

		if len(dimension_values) > 1:
			grand_total_row = create_total_rows([None], company_currency, None)[None]
			grand_total_row.update({
				"account_name": _("Grand Total"),
				"account_display": _("Grand Total"),
				"dimension_value": ""
			})

			if filters.show_tree:
				grand_total_row["indent"] = 0

			for dim_value in dimension_values:
				for field in value_fields:
					grand_total_row[field] += total_rows[dim_value][field]

			data.append(grand_total_row)
	else:
		if None in total_rows:
			if filters.show_tree:
				total_rows[None]["indent"] = 0
			data.append(total_rows[None])

	return data

def has_account_value(data):
	for field in value_fields:
		if abs(data.get(field, 0)) >= 0.005:
			return True
	return False


def build_account_row(account, filters, company_currency, dimension_value=None):
	row = {
		"account": account.name,
		"account_number": account.account_number,
		"account_name": account.account_name,
		"account_display": f"{account.account_number} - {account.account_name}" if account.account_number else account.account_name,
		"parent_account": account.parent_account,
		"is_group": account.is_group,
		"from_date": filters.from_date,
		"to_date": filters.to_date,
		"currency": company_currency,
	}

	if filters.show_tree:
		row["indent"] = account.indent

	if dimension_value is not None:
		row["dimension_value"] = dimension_value

	return row


def get_columns(filters, dimension_field=None):
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
				"width": 300,
			},
		]

	if dimension_field:
		dimension_label = get_dimension_label(dimension_field)
		columns.append({
			"fieldname": "dimension_value",
			"label": _(dimension_label),
			"fieldtype": "Data",
			"width": 150
		})

	columns += [
		{
			"fieldname": "opening_debit",
			"label": _("Opening (Dr)"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
		{
			"fieldname": "opening_credit",
			"label": _("Opening (Cr)"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
		{
			"fieldname": "debit",
			"label": _("Debit"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
		{
			"fieldname": "credit",
			"label": _("Credit"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
		{
			"fieldname": "closing_debit",
			"label": _("Closing (Dr)"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
		{
			"fieldname": "closing_credit",
			"label": _("Closing (Cr)"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		}
	]

	return columns


def prepare_opening_closing(row):
	dr_or_cr = "debit" if row["root_type"] in ["Asset", "Equity", "Expense"] else "credit"
	reverse_dr_or_cr = "credit" if dr_or_cr == "debit" else "debit"

	for col_type in ["opening", "closing"]:
		valid_col = col_type + "_" + dr_or_cr
		reverse_col = col_type + "_" + reverse_dr_or_cr
		row[valid_col] -= row[reverse_col]
		if row[valid_col] < 0:
			row[reverse_col] = abs(row[valid_col])
			row[valid_col] = 0.0
		else:
			row[reverse_col] = 0.0
