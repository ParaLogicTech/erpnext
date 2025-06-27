# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe, erpnext
from frappe import _
from frappe.utils import flt, getdate, formatdate, cstr
from erpnext.accounts.report.financial_statements \
	import filter_accounts, set_gl_entries_by_account, filter_out_zero_value_rows
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions, \
	get_dimension_with_children

value_fields = ("opening_debit", "opening_credit", "debit", "credit", "closing_debit", "closing_credit")


def execute(filters=None):
	validate_filters(filters)
	group_by_field = None
	dimension_values = None

	if filters and filters.get("group_by"):
		group_by_field = get_group_by_field(filters.group_by)
		if group_by_field:
			dimension_values = get_dimension_values(filters, group_by_field)

	data = get_data(filters, group_by_field, dimension_values)
	columns = get_columns(filters, group_by_field, dimension_values)
	return columns, data


def get_group_by_field(group_by_value):
	"""Get the field name from the group by value dynamically"""
	if not group_by_value:
		return None

	if group_by_value == "Cost Center":
		return "cost_center"
	elif group_by_value == "Project":
		return "project"

	accounting_dimensions = get_accounting_dimensions(as_list=False)
	for dimension in accounting_dimensions:
		if dimension.document_type == group_by_value:
			return dimension.fieldname

	return None


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


def get_data(filters, group_by_field=None, dimension_values=None):
	accounts = frappe.db.sql("""
		select name, account_number, parent_account, account_name, root_type, report_type, lft, rgt
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

	gl_entries_by_account = get_gl_entries_with_grouping(filters, min_lft, max_rgt, group_by_field)
	opening_balances = get_opening_balances_with_grouping(filters, group_by_field)
	total_row = calculate_values_with_grouping(accounts, gl_entries_by_account, opening_balances, filters,
		company_currency, dimension_values, group_by_field)
	accumulate_values_into_parents_with_grouping(accounts, accounts_by_name, dimension_values)
	data = prepare_data_with_grouping(accounts, filters, total_row, parent_children_map, company_currency,
		dimension_values)

	if not filters.get("show_zero_values"):
		data = [row for row in data if row.get("has_value", True)]

	set_zero_for_group_accounts_with_grouping(data, parent_children_map, dimension_values)

	return data


def get_dimension_values(filters, group_by_field):
	additional_conditions = []
	query_filters = {
		"company": filters.company,
		"from_date": filters.from_date,
		"to_date": filters.to_date
	}

	if not flt(filters.with_period_closing_entry):
		additional_conditions.append("voucher_type != 'Period Closing Voucher'")

	if filters.cost_center:
		if group_by_field == 'cost_center':
			additional_conditions.append("cost_center = %(cost_center)s")
			query_filters["cost_center"] = filters.cost_center
		else:
			cost_center_data = frappe.db.get_value('Cost Center', filters.cost_center, 'lft, rgt')
			if cost_center_data:
				lft, rgt = cost_center_data
				additional_conditions.append("""cost_center in (select name from `tabCost Center`
					where lft >= {0} and rgt <= {1})""".format(lft, rgt))

	if filters.project:
		if group_by_field == 'project':
			additional_conditions.append("project = %(project)s")
			query_filters["project"] = filters.project
		else:
			additional_conditions.append("project = %(project)s")
			query_filters["project"] = filters.project

	accounting_dimensions = get_accounting_dimensions(as_list=False)
	if accounting_dimensions:
		for dimension in accounting_dimensions:
			if filters.get(dimension.fieldname):
				if group_by_field == dimension.fieldname:
					additional_conditions.append(f"{dimension.fieldname} = %({dimension.fieldname})s")
					query_filters[dimension.fieldname] = filters.get(dimension.fieldname)
				else:
					if frappe.get_cached_value('DocType', dimension.document_type, 'is_tree'):
						filters[dimension.fieldname] = get_dimension_with_children(dimension.document_type,
																				   filters.get(dimension.fieldname))
						additional_conditions.append(f"{dimension.fieldname} in %({dimension.fieldname})s")
					else:
						additional_conditions.append(f"{dimension.fieldname} = %({dimension.fieldname})s")
					query_filters[dimension.fieldname] = filters.get(dimension.fieldname)

	if filters.finance_book:
		fb_conditions = "finance_book = %(finance_book)s"
		if filters.include_default_book_entries:
			fb_conditions = "(finance_book in (%(finance_book)s, %(company_fb)s, '') OR finance_book IS NULL)"
		additional_conditions.append(fb_conditions)
		query_filters["finance_book"] = filters.finance_book
		query_filters["company_fb"] = frappe.db.get_value("Company", filters.company, 'default_finance_book')

	additional_conditions = " and {0}".format(" and ".join(additional_conditions)) if additional_conditions else ""

	sql = """
		select distinct {group_by_field}
		from `tabGL Entry`
		where company = %(company)s
			and posting_date between %(from_date)s and %(to_date)s
			and {group_by_field} is not null
			and {group_by_field} != ''
			{additional_conditions}
		order by {group_by_field}
	""".format(group_by_field=group_by_field, additional_conditions=additional_conditions)

	result = frappe.db.sql(sql, query_filters, as_dict=False)
	return [row[0] for row in result if row[0]]


def get_gl_entries_with_grouping(filters, min_lft, max_rgt, group_by_field):
	additional_conditions = []
	query_filters = {
		"company": filters.company,
		"from_date": filters.from_date,
		"to_date": filters.to_date
	}

	if not flt(filters.with_period_closing_entry):
		additional_conditions.append("voucher_type != 'Period Closing Voucher'")

	if filters.cost_center:
		if group_by_field == 'cost_center':
			additional_conditions.append("cost_center = %(cost_center)s")
			query_filters["cost_center"] = filters.cost_center
		else:
			cost_center_data = frappe.db.get_value('Cost Center', filters.cost_center, 'lft, rgt')
			if cost_center_data:
				lft, rgt = cost_center_data
				additional_conditions.append("""cost_center in (select name from `tabCost Center`
					where lft >= {0} and rgt <= {1})""".format(lft, rgt))

	if filters.project:
		if group_by_field == 'project':
			additional_conditions.append("project = %(project)s")
			query_filters["project"] = filters.project
		else:
			additional_conditions.append("project = %(project)s")
			query_filters["project"] = filters.project

	accounting_dimensions = get_accounting_dimensions(as_list=False)
	if accounting_dimensions:
		for dimension in accounting_dimensions:
			if filters.get(dimension.fieldname):
				if group_by_field == dimension.fieldname:
					additional_conditions.append(f"{dimension.fieldname} = %({dimension.fieldname})s")
					query_filters[dimension.fieldname] = filters.get(dimension.fieldname)
				else:
					if frappe.get_cached_value('DocType', dimension.document_type, 'is_tree'):
						filters[dimension.fieldname] = get_dimension_with_children(dimension.document_type,
																				   filters.get(dimension.fieldname))
						additional_conditions.append(f"{dimension.fieldname} in %({dimension.fieldname})s")
					else:
						additional_conditions.append(f"{dimension.fieldname} = %({dimension.fieldname})s")
					query_filters[dimension.fieldname] = filters.get(dimension.fieldname)

	if filters.finance_book:
		fb_conditions = "finance_book = %(finance_book)s"
		if filters.include_default_book_entries:
			fb_conditions = "(finance_book in (%(finance_book)s, %(company_fb)s, '') OR finance_book IS NULL)"
		additional_conditions.append(fb_conditions)

	additional_conditions = " and {0}".format(" and ".join(additional_conditions)) if additional_conditions else ""

	sql = """
		select account, {group_by_field},
			sum(debit) as debit, sum(credit) as credit,
			is_opening
		from `tabGL Entry`
		where company = %(company)s
			and posting_date between %(from_date)s and %(to_date)s
			and account in (select name from `tabAccount` where lft >= {min_lft} and rgt <= {max_rgt})
			and {group_by_field} is not null
			and {group_by_field} != '' {additional_conditions}
		group by account, {group_by_field}, is_opening
		order by account, {group_by_field}
	""".format(group_by_field=group_by_field, min_lft=min_lft, max_rgt=max_rgt,
			   additional_conditions=additional_conditions)

	entries = frappe.db.sql(sql, query_filters, as_dict=True)
	gl_entries_by_account = {}
	for entry in entries:
		account = entry.account
		if account not in gl_entries_by_account:
			gl_entries_by_account[account] = []
		gl_entries_by_account[account].append(entry)
	return gl_entries_by_account


def get_opening_balances_with_grouping(filters, group_by_field):
	balance_sheet_opening = get_rootwise_opening_balances_with_grouping(filters, "Balance Sheet", group_by_field)
	pl_opening = get_rootwise_opening_balances_with_grouping(filters, "Profit and Loss", group_by_field)
	for account, dimensions in pl_opening.items():
		if account in balance_sheet_opening:
			balance_sheet_opening[account].update(dimensions)
		else:
			balance_sheet_opening[account] = dimensions
	return balance_sheet_opening


def get_rootwise_opening_balances_with_grouping(filters, report_type, group_by_field):
	additional_conditions = []
	if not filters.show_unclosed_fy_pl_balances and report_type == "Profit and Loss":
		additional_conditions.append("posting_date >= %(year_start_date)s")

	if not flt(filters.with_period_closing_entry):
		additional_conditions.append("voucher_type != 'Period Closing Voucher'")

	if filters.cost_center:
		if group_by_field == 'cost_center':
			additional_conditions.append("cost_center = %(cost_center)s")
		else:
			cost_center_data = frappe.db.get_value('Cost Center', filters.cost_center, 'lft, rgt')
			if cost_center_data:
				lft, rgt = cost_center_data
				additional_conditions.append("""cost_center in (select name from `tabCost Center`
					where lft >= {0} and rgt <= {1})""".format(lft, rgt))

	if filters.project:
		if group_by_field == 'project':
			additional_conditions.append("project = %(project)s")
		else:
			additional_conditions.append("project = %(project)s")

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

	if filters.cost_center and group_by_field == 'cost_center':
		query_filters["cost_center"] = filters.cost_center

	if accounting_dimensions:
		for dimension in accounting_dimensions:
			if filters.get(dimension.fieldname):
				if group_by_field == dimension.fieldname:
					additional_conditions.append(f"{dimension.fieldname} = %({dimension.fieldname})s")
					query_filters[dimension.fieldname] = filters.get(dimension.fieldname)
				else:
					if frappe.get_cached_value('DocType', dimension.document_type, 'is_tree'):
						filters[dimension.fieldname] = get_dimension_with_children(dimension.document_type,
																				   filters.get(dimension.fieldname))
						additional_conditions.append(f"{dimension.fieldname} in %({dimension.fieldname})s")
					else:
						additional_conditions.append(f"{dimension.fieldname} = %({dimension.fieldname})s")
					query_filters[dimension.fieldname] = filters.get(dimension.fieldname)

	if filters.finance_book:
		fb_conditions = "finance_book = %(finance_book)s"
		if filters.include_default_book_entries:
			fb_conditions = "(finance_book in (%(finance_book)s, %(company_fb)s, '') OR finance_book IS NULL)"
		additional_conditions.append(fb_conditions)

	additional_conditions = " and {0}".format(" and ".join(additional_conditions)) if additional_conditions else ""

	sql = """
		select account, {group_by_field},
			sum(debit) as opening_debit, sum(credit) as opening_credit
		from `tabGL Entry`
		where company = %(company)s
			{additional_conditions}
			and (posting_date < %(from_date)s or is_opening = 'Yes')
			and account in (select name from `tabAccount` where report_type=%(report_type)s)
			and {group_by_field} is not null
			and {group_by_field} != ''
		group by account, {group_by_field}
	""".format(group_by_field=group_by_field, additional_conditions=additional_conditions)

	gle = frappe.db.sql(sql, query_filters, as_dict=True)
	opening = {}
	for d in gle:
		account = d.account
		dimension = d.get(group_by_field)
		if account not in opening:
			opening[account] = {}
		opening[account][dimension] = {
			'opening_debit': d.opening_debit or 0,
			'opening_credit': d.opening_credit or 0
		}
	return opening


def calculate_values_with_grouping(accounts, gl_entries_by_account, opening_balances, filters, company_currency,
								   dimension_values, group_by_field):
	init_values = {}
	for dim in dimension_values:
		init_values[f"opening_{dim}"] = 0.0
		init_values[f"movement_{dim}"] = 0.0
		init_values[f"closing_{dim}"] = 0.0

	total_row = {
		"account": "'" + _("Total") + "'",
		"account_name": "'" + _("Total") + "'",
		"warn_if_negative": True,
		"parent_account": None,
		"indent": 0,
		"has_value": True,
		"currency": company_currency
	}
	total_row.update(init_values)

	for d in accounts:
		d.update(init_values.copy())
		account_opening = opening_balances.get(d.name, {})

		for dim in dimension_values:
			dim_opening = account_opening.get(dim, {})
			opening_debit = dim_opening.get("opening_debit", 0)
			opening_credit = dim_opening.get("opening_credit", 0)

			d[f"opening_{dim}"] = opening_debit - opening_credit

		# Calculate movement and closing for each dimension
		for dim in dimension_values:
			debit_total = 0.0
			credit_total = 0.0

			for entry in gl_entries_by_account.get(d.name, []):
				if cstr(entry.is_opening) != "Yes" and entry.get(group_by_field) == dim:
					debit_total += flt(entry.debit)
					credit_total += flt(entry.credit)

			d[f"movement_{dim}"] = debit_total - credit_total

			d[f"closing_{dim}"] = d[f"opening_{dim}"] + d[f"movement_{dim}"]

		for field_dim in init_values.keys():
			total_row[field_dim] += d[field_dim]

	return total_row


def accumulate_values_into_parents_with_grouping(accounts, accounts_by_name, dimension_values):
	for d in reversed(accounts):
		if d.parent_account:
			parent = accounts_by_name[d.parent_account]
			for field_type in ["opening", "movement", "closing"]:
				for dim in dimension_values:
					key = f"{field_type}_{dim}"
					parent[key] += d[key]


def prepare_data_with_grouping(accounts, filters, total_row, parent_children_map, company_currency, dimension_values):
	data = []
	for d in accounts:
		has_value = False
		row = {
			"account": d.name,
			"parent_account": d.parent_account,
			"indent": d.indent,
			"from_date": filters.from_date,
			"to_date": filters.to_date,
			"currency": company_currency,
			"account_name": ('{} - {}'.format(d.account_number, d.account_name)
							 if d.account_number else d.account_name)
		}

		# Add the combined values for each dimension
		for field_type in ["opening", "movement", "closing"]:
			for dim in dimension_values:
				key = f"{field_type}_{dim}"
				row[key] = flt(d.get(key, 0.0), 3)
				if abs(row[key]) >= 0.005:
					has_value = True

		row["has_value"] = has_value
		data.append(row)

	data.extend([{}, total_row])
	return data


def set_zero_for_group_accounts_with_grouping(data, parent_children_map, dimension_values):
	"""Hide parent account totals for grouped reports while keeping the account structure visible"""
	for d in data:
		if d.get('account') and parent_children_map.get(d['account']):
			# This is a parent account (has children), so hide its totals
			for field_type in ["opening", "movement", "closing"]:
				for dim in dimension_values:
					key = f"{field_type}_{dim}"
					if key in d:
						del d[key]


def get_columns(filters=None, group_by_field=None, dimension_values=None):
	if dimension_values is None:
		dimension_values = get_dimension_values(filters, group_by_field)

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

	# Group columns by type: Opening, Movement, Closing
	for dim_value in dimension_values:
		columns.append({
			"fieldname": f"opening_{dim_value}",
			"label": f"Opening {dim_value}",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		})

	for dim_value in dimension_values:
		columns.append({
			"fieldname": f"movement_{dim_value}",
			"label": f"Movement {dim_value}",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		})

	for dim_value in dimension_values:
		columns.append({
			"fieldname": f"closing_{dim_value}",
			"label": f"Closing {dim_value}",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		})

	return columns
