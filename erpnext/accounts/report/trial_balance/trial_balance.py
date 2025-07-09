# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe, erpnext
from frappe import _, unscrub
from frappe.utils import flt, getdate, formatdate, cstr
from erpnext.accounts.report.financial_statements \
	import filter_accounts, set_gl_entries_by_account, filter_out_zero_value_rows
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions, \
	get_dimension_with_children, get_all_dimension_fields

value_fields = ("opening_debit", "opening_credit", "debit", "credit", "closing_debit", "closing_credit")


def execute(filters=None):
	validate_filters(filters)

	data = get_data(filters)
	columns = get_columns(filters)
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

	if filters.project:
		filters.project = [filters.project]

	if filters.dimension_field and filters.dimension_field not in get_all_dimension_fields():
		frappe.throw(_("Invalid Dimension Field {0}").format(filters.dimension_field))


def get_data(filters):
	accounts = frappe.db.sql("""
		select name, account_number, parent_account, account_name, root_type, report_type, lft, rgt, is_group
		from `tabAccount`
		where company = %s order by lft
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

	opening_balances = get_opening_balances(filters, dimension_field=filters.dimension_field)

	gl_entries_by_account = {}
	set_gl_entries_by_account(
		filters.company, filters.from_date, filters.to_date,
		min_lft, max_rgt, filters, gl_entries_by_account,
		ignore_closing_entries=not flt(filters.with_period_closing_entry),
		dimension_field=filters.dimension_field,
	)

	total_rows = calculate_values(accounts, gl_entries_by_account, opening_balances, company_currency,
		dimension_field=filters.dimension_field)
	accumulate_values_into_parents(accounts, accounts_by_name)

	data = prepare_data(accounts, filters, total_rows, parent_children_map, company_currency,
		dimension_field=filters.dimension_field)
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

	select_fields_str = ", ".join(select_fields)

	cost_center_join = ""
	if dimension_field == 'cost_center':
		cost_center_join = "LEFT JOIN `tabCost Center` cc ON gle.cost_center = cc.name"

	group_by = "gle.account"
	if dimension_field:
		group_by = f"gle.account, gle.{dimension_field}"

	gl_data = frappe.db.sql(f"""
		select {select_fields_str}
		from `tabGL Entry` gle
		{cost_center_join}
		where gle.company = %(company)s
			{additional_conditions}
			and (gle.posting_date < %(from_date)s or gle.is_opening = 'Yes')
			and account in (select acc.name from `tabAccount` acc where acc.report_type = %(report_type)s)
		group by {group_by}
	""", query_filters, as_dict=True)

	opening_balances = frappe._dict()
	for gle in gl_data:
		account_opening = opening_balances.setdefault(gle.account, frappe._dict({
			"account": gle.account, "opening_debit": 0, "opening_credit": 0, "dimensions": {},
		}))

		account_opening.opening_debit += gle.opening_debit
		account_opening.opening_credit += gle.opening_credit

		if dimension_field:
			dimension_value = cstr(gle.get(dimension_field))
			dimension_opening = account_opening.dimensions.setdefault(dimension_value, frappe._dict({
				dimension_field: dimension_value,
				"opening_debit": 0,
				"opening_credit": 0,
			}))

			dimension_opening.opening_debit += gle.opening_debit
			dimension_opening.opening_credit += gle.opening_credit

	hooks = frappe.get_hooks('get_opening_account_balances')
	for method in hooks:
		hooked_opening_balances = frappe.get_attr(method)(filters)
		if hooked_opening_balances is None:
			continue

		for account, op in hooked_opening_balances.items():
			account_opening = opening_balances.setdefault(account, frappe._dict({
				"account": account, "opening_debit": 0, "opening_credit": 0, "dimensions": {},
			}))

			if op.opening_balance >= 0:
				account_opening['opening_debit'] += op.opening_balance
			else:
				account_opening['opening_credit'] += -1 * op.opening_balance

			if dimension_field:
				dimension_value = cstr(op.get(dimension_field))
				dimension_opening = account_opening.dimensions.setdefault(dimension_value, frappe._dict({
					dimension_field: dimension_value,
					"opening_debit": 0,
					"opening_credit": 0,
				}))

				if op.opening_balance >= 0:
					dimension_opening['opening_debit'] += op.opening_balance
				else:
					dimension_opening['opening_credit'] += -1 * op.opening_balance

	return opening_balances


def calculate_values(accounts, gl_entries_by_account, opening_balances, company_currency, dimension_field=None):
	init = frappe._dict({
		"opening_debit": 0.0,
		"opening_credit": 0.0,
		"debit": 0.0,
		"credit": 0.0,
		"closing_debit": 0.0,
		"closing_credit": 0.0
	})

	total_row_init = frappe._dict({
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
		"indent": 0,
		"has_value": True,
		"currency": company_currency
	})
	dimension_totals = {}
	grand_total_row = total_row_init.copy()

	def get_dimension_object(account_obj, dimension_field, dimension_value):
		if dimension_value not in account_obj.dimensions:
			dimension_object = account_obj.dimensions[dimension_value] = dim_init.copy()
			dimension_object[dimension_field] = dimension_value

		return account_obj.dimensions[dimension_value]

	for acc in accounts:
		acc.update(init.copy())
		dim_init = acc.copy()
		acc["dimensions"] = {}

		account_opening = opening_balances.get(acc.name, frappe._dict())

		# add opening
		acc["opening_debit"] = flt(account_opening.get("opening_debit"))
		acc["opening_credit"] = flt(account_opening.get("opening_credit"))

		for dimension_value, dimension_opening in account_opening.get("dimensions", {}).items():
			dim = get_dimension_object(acc, dimension_field, dimension_value)
			dim["opening_debit"] = flt(dimension_opening.get("opening_debit"))
			dim["opening_credit"] = flt(dimension_opening.get("opening_credit"))

		# add movement
		for entry in gl_entries_by_account.get(acc.name, []):
			if cstr(entry.is_opening) == "Yes":
				continue

			acc["debit"] += flt(entry.debit)
			acc["credit"] += flt(entry.credit)

			if dimension_field:
				dimension_value = cstr(entry.get(dimension_field))
				dim = get_dimension_object(acc, dimension_field, dimension_value)
				dim["debit"] += flt(entry.debit)
				dim["credit"] += flt(entry.credit)

		# calculate closing
		acc["closing_debit"] = acc["opening_debit"] + acc["debit"]
		acc["closing_credit"] = acc["opening_credit"] + acc["credit"]
		prepare_opening_closing(acc)

		for dimension_value, dim in acc.get("dimensions", {}).items():
			dim["closing_debit"] = dim["opening_debit"] + dim["debit"]
			dim["closing_credit"] = dim["opening_credit"] + dim["credit"]
			prepare_opening_closing(dim)

		# accumulate total rows
		if dimension_field:
			for dimension_value, dim in acc.get("dimensions", {}).items():
				dimension_total_row = dimension_totals.get(dimension_value)
				if not dimension_total_row:
					dimension_total_row = dimension_totals[dimension_value] = total_row_init.copy()
					dimension_total_row["account_name"] = _("Dimension Total")
					dimension_total_row["account_display"] = _("Dimension Total")
					dimension_total_row[dimension_field] = dimension_value

				for field in value_fields:
					dimension_total_row[field] += dim[field]
					grand_total_row[field] += dim[field]
		else:
			for field in value_fields:
				grand_total_row[field] += acc[field]

	if dimension_field:
		total_rows = sorted(dimension_totals.values(), key=lambda d: dimension_sorter(d, dimension_field)) + [{}, grand_total_row]
	else:
		total_rows = [grand_total_row]

	return total_rows


def accumulate_values_into_parents(accounts, accounts_by_name):
	for d in reversed(accounts):
		if d.parent_account:
			for key in value_fields:
				accounts_by_name[d.parent_account][key] += d[key]


def set_zero_for_group_accounts(data, parent_children_map):
	for d in data:
		if d.get('account') and parent_children_map.get(d['account']):
			for key in value_fields:
				del d[key]


def prepare_data(accounts, filters, total_rows, parent_children_map, company_currency, dimension_field=None):
	data = []

	for acc in accounts:
		# Prepare opening closing for group account
		if parent_children_map.get(acc.account):
			prepare_opening_closing(acc)

		if dimension_field and not acc.is_group:
			sources = acc.dimensions.values() or [acc]
		else:
			sources = [acc]

		account_rows = []

		for d in sources:
			has_value = False
			row = {
				"account": d.name,
				"account_number": d.account_number,
				"account_name": d.account_name,
				"account_display": f"{d.account_number} - {d.account_name}" if d.account_number else d.account_name,
				"parent_account": d.parent_account,
				"is_group": d.is_group,
				"from_date": filters.from_date,
				"to_date": filters.to_date,
				"currency": company_currency,
			}

			if dimension_field:
				dimension_value = cstr(d.get(dimension_field))
				row[dimension_field] = dimension_value

			if filters.show_tree:
				row["indent"] = d.indent

			for key in value_fields:
				row[key] = flt(d.get(key, 0.0), 3)

				if abs(row[key]) >= 0.005:
					# ignore zero values
					has_value = True

			row["has_value"] = has_value
			if not d.is_group or filters.show_tree:
				account_rows.append(row)

		if dimension_field:
			account_rows = sorted(account_rows, key=lambda d: dimension_sorter(d, dimension_field))

		data += account_rows

	data.append({})
	data += total_rows

	return data


def get_columns(filters):
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
				"width": 250,
			},
		]

	if filters.dimension_field:
		dimension_details = get_dimension_column_details(filters.dimension_field)
		columns.append({
			"fieldname": filters.dimension_field,
			"label": dimension_details.label,
			"fieldtype": "Link" if dimension_details.document_type else "Data",
			"options": dimension_details.document_type,
			"width": 150,
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


def get_dimension_column_details(dimension_field):
	accounting_dimensions = get_accounting_dimensions(as_list=False)
	for dimension in accounting_dimensions:
		if dimension.fieldname == dimension_field:
			return frappe._dict({
				"label": _(dimension.label),
				"document_type": dimension.document_type,
			})

	label = unscrub(dimension_field)
	return frappe._dict({
		"label": _(label),
		"document_type": label if label in ("Cost Center", "Project") else None,
	})


def dimension_sorter(data, dimension_field):
	dimension_value = data.get(dimension_field)
	return not dimension_value, dimension_value


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
