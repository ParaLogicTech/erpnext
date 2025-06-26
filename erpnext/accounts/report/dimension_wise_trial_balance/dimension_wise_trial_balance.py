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

GROUP_BY_MAPPING = {
	"Group by Cost Center": "cost_center",
	"Group by Project": "project",
	"Group by Vehicle Workshop Division": "vehicle_workshop_division",
	"Group by Vehicle Brand": "applies_to_item_brand",
	"Group by Vehicle": "applies_to_vehicle",
	"Group by Item Group": "item_group",
	"Group by Customer Group": "customer_group",
	"Group by Branch": "branch"
}

def execute(filters=None):
	validate_filters(filters)
	group_by_field = None
	dimension_values = None
	if filters and filters.get("group_by") in GROUP_BY_MAPPING:
		group_by_field = GROUP_BY_MAPPING[filters.group_by]
		dimension_values = get_dimension_values(filters, group_by_field)
	data = get_data(filters, group_by_field, dimension_values)
	columns = get_columns(filters, group_by_field, dimension_values)
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
		frappe.msgprint(_("From Date should be within the Fiscal Year. Assuming From Date = {0}").format(formatdate(filters.year_start_date)))
		filters.from_date = filters.year_start_date

	if (filters.to_date < filters.year_start_date) or (filters.to_date > filters.year_end_date):
		frappe.msgprint(_("To Date should be within the Fiscal Year. Assuming To Date = {0}").format(formatdate(filters.year_end_date)))
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

	gl_entries_by_account = {}

	if group_by_field:
		gl_entries_by_account = get_gl_entries_with_grouping(filters, min_lft, max_rgt, group_by_field)
		opening_balances = get_opening_balances_with_grouping(filters, group_by_field)
		total_row = calculate_values_with_grouping(accounts, gl_entries_by_account, opening_balances, filters, company_currency, dimension_values, group_by_field)
		accumulate_values_into_parents_with_grouping(accounts, accounts_by_name, dimension_values)
		data = prepare_data_with_grouping(accounts, filters, total_row, parent_children_map, company_currency, dimension_values)
	else:
		opening_balances = get_opening_balances(filters)
		if filters.project:
			filters.project = [filters.project]
		set_gl_entries_by_account(filters.company, filters.from_date, filters.to_date,
			min_lft, max_rgt, filters, gl_entries_by_account,
			ignore_closing_entries=not flt(filters.with_period_closing_entry))
		total_row = calculate_values(accounts, gl_entries_by_account, opening_balances, filters, company_currency)
		accumulate_values_into_parents(accounts, accounts_by_name)
		data = prepare_data(accounts, filters, total_row, parent_children_map, company_currency)

	data = filter_out_zero_value_rows(data, parent_children_map, show_zero_values=filters.get("show_zero_values"))
	if not group_by_field:
		set_zero_for_group_accounts(data, parent_children_map)
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
			lft, rgt = frappe.db.get_value('Cost Center', filters.cost_center, ['lft', 'rgt'])
			additional_conditions.append("""cost_center in (select name from `tabCost Center`
				where lft >= {0} and rgt <= {1})""".format(lft, rgt))

	if filters.project:
		if group_by_field == 'project':
			additional_conditions.append("project = %(project)s")
			query_filters["project"] = filters.project
		else:
			additional_conditions.append("project = %(project)s")
			query_filters["project"] = filters.project

	if filters.branch:
		if group_by_field == 'branch':
			additional_conditions.append("branch = %(branch)s")
			query_filters["branch"] = filters.branch
		else:
			additional_conditions.append("branch = %(branch)s")
			query_filters["branch"] = filters.branch

	if filters.vehicle_workshop_division:
		if group_by_field == 'vehicle_workshop_division':
			additional_conditions.append("vehicle_workshop_division = %(vehicle_workshop_division)s")
			query_filters["vehicle_workshop_division"] = filters.vehicle_workshop_division
		else:
			additional_conditions.append("vehicle_workshop_division = %(vehicle_workshop_division)s")
			query_filters["vehicle_workshop_division"] = filters.vehicle_workshop_division

	if filters.applies_to_item_brand:
		if group_by_field == 'applies_to_item_brand':
			additional_conditions.append("applies_to_item_brand = %(applies_to_item_brand)s")
			query_filters["applies_to_item_brand"] = filters.applies_to_item_brand
		else:
			additional_conditions.append("applies_to_item_brand = %(applies_to_item_brand)s")
			query_filters["applies_to_item_brand"] = filters.applies_to_item_brand

	if filters.applies_to_vehicle:
		if group_by_field == 'applies_to_vehicle':
			additional_conditions.append("applies_to_vehicle = %(applies_to_vehicle)s")
			query_filters["applies_to_vehicle"] = filters.applies_to_vehicle
		else:
			additional_conditions.append("applies_to_vehicle = %(applies_to_vehicle)s")
			query_filters["applies_to_vehicle"] = filters.applies_to_vehicle

	if filters.item_group:
		if group_by_field == 'item_group':
			additional_conditions.append("item_group = %(item_group)s")
			query_filters["item_group"] = filters.item_group
		else:
			additional_conditions.append("item_group = %(item_group)s")
			query_filters["item_group"] = filters.item_group

	if filters.customer_group:
		if group_by_field == 'customer_group':
			additional_conditions.append("customer_group = %(customer_group)s")
			query_filters["customer_group"] = filters.customer_group
		else:
			additional_conditions.append("customer_group = %(customer_group)s")
			query_filters["customer_group"] = filters.customer_group

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
			lft, rgt = frappe.db.get_value('Cost Center', filters.cost_center, ['lft', 'rgt'])
			additional_conditions.append("""cost_center in (select name from `tabCost Center`
				where lft >= {0} and rgt <= {1})""".format(lft, rgt))

	if filters.project:
		if group_by_field == 'project':
			additional_conditions.append("project = %(project)s")
			query_filters["project"] = filters.project
		else:
			additional_conditions.append("project = %(project)s")
			query_filters["project"] = filters.project

	if filters.branch:
		if group_by_field == 'branch':
			additional_conditions.append("branch = %(branch)s")
			query_filters["branch"] = filters.branch
		else:
			additional_conditions.append("branch = %(branch)s")
			query_filters["branch"] = filters.branch

	if filters.vehicle_workshop_division:
		if group_by_field == 'vehicle_workshop_division':
			additional_conditions.append("vehicle_workshop_division = %(vehicle_workshop_division)s")
			query_filters["vehicle_workshop_division"] = filters.vehicle_workshop_division
		else:
			additional_conditions.append("vehicle_workshop_division = %(vehicle_workshop_division)s")
			query_filters["vehicle_workshop_division"] = filters.vehicle_workshop_division

	if filters.applies_to_item_brand:
		if group_by_field == 'applies_to_item_brand':
			additional_conditions.append("applies_to_item_brand = %(applies_to_item_brand)s")
			query_filters["applies_to_item_brand"] = filters.applies_to_item_brand
		else:
			additional_conditions.append("applies_to_item_brand = %(applies_to_item_brand)s")
			query_filters["applies_to_item_brand"] = filters.applies_to_item_brand

	if filters.applies_to_vehicle:
		if group_by_field == 'applies_to_vehicle':
			additional_conditions.append("applies_to_vehicle = %(applies_to_vehicle)s")
			query_filters["applies_to_vehicle"] = filters.applies_to_vehicle
		else:
			additional_conditions.append("applies_to_vehicle = %(applies_to_vehicle)s")
			query_filters["applies_to_vehicle"] = filters.applies_to_vehicle

	if filters.item_group:
		if group_by_field == 'item_group':
			additional_conditions.append("item_group = %(item_group)s")
			query_filters["item_group"] = filters.item_group
		else:
			additional_conditions.append("item_group = %(item_group)s")
			query_filters["item_group"] = filters.item_group

	if filters.customer_group:
		if group_by_field == 'customer_group':
			additional_conditions.append("customer_group = %(customer_group)s")
			query_filters["customer_group"] = filters.customer_group
		else:
			additional_conditions.append("customer_group = %(customer_group)s")
			query_filters["customer_group"] = filters.customer_group

	if filters.finance_book:
		fb_conditions = "finance_book = %(finance_book)s"
		if filters.include_default_book_entries:
			fb_conditions = "(finance_book in (%(finance_book)s, %(company_fb)s, '') OR finance_book IS NULL)"
		additional_conditions.append(fb_conditions)
		query_filters["finance_book"] = filters.finance_book
		query_filters["company_fb"] = frappe.db.get_value("Company", filters.company, 'default_finance_book')

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
			lft, rgt = frappe.db.get_value('Cost Center', filters.cost_center, ['lft', 'rgt'])
			additional_conditions.append("""cost_center in (select name from `tabCost Center`
				where lft >= {0} and rgt <= {1})""".format(lft, rgt))

	if filters.project:
		if group_by_field == 'project':
			additional_conditions.append("project = %(project)s")
		else:
			additional_conditions.append("project = %(project)s")

	if filters.branch:
		if group_by_field == 'branch':
			additional_conditions.append("branch = %(branch)s")
		else:
			additional_conditions.append("branch = %(branch)s")

	if filters.vehicle_workshop_division:
		if group_by_field == 'vehicle_workshop_division':
			additional_conditions.append("vehicle_workshop_division = %(vehicle_workshop_division)s")
		else:
			additional_conditions.append("vehicle_workshop_division = %(vehicle_workshop_division)s")

	if filters.applies_to_item_brand:
		if group_by_field == 'applies_to_item_brand':
			additional_conditions.append("applies_to_item_brand = %(applies_to_item_brand)s")
		else:
			additional_conditions.append("applies_to_item_brand = %(applies_to_item_brand)s")

	if filters.applies_to_vehicle:
		if group_by_field == 'applies_to_vehicle':
			additional_conditions.append("applies_to_vehicle = %(applies_to_vehicle)s")
		else:
			additional_conditions.append("applies_to_vehicle = %(applies_to_vehicle)s")

	if filters.item_group:
		if group_by_field == 'item_group':
			additional_conditions.append("item_group = %(item_group)s")
		else:
			additional_conditions.append("item_group = %(item_group)s")

	if filters.customer_group:
		if group_by_field == 'customer_group':
			additional_conditions.append("customer_group = %(customer_group)s")
		else:
			additional_conditions.append("customer_group = %(customer_group)s")

	if filters.finance_book:
		fb_conditions = "finance_book = %(finance_book)s"
		if filters.include_default_book_entries:
			fb_conditions = "(finance_book in (%(finance_book)s, %(company_fb)s, '') OR finance_book IS NULL)"
		additional_conditions.append(fb_conditions)

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
	if filters.branch and group_by_field == 'branch':
		query_filters["branch"] = filters.branch
	if filters.vehicle_workshop_division and group_by_field == 'vehicle_workshop_division':
		query_filters["vehicle_workshop_division"] = filters.vehicle_workshop_division
	if filters.applies_to_item_brand and group_by_field == 'applies_to_item_brand':
		query_filters["applies_to_item_brand"] = filters.applies_to_item_brand
	if filters.applies_to_vehicle and group_by_field == 'applies_to_vehicle':
		query_filters["applies_to_vehicle"] = filters.applies_to_vehicle
	if filters.item_group and group_by_field == 'item_group':
		query_filters["item_group"] = filters.item_group
	if filters.customer_group and group_by_field == 'customer_group':
		query_filters["customer_group"] = filters.customer_group

	if filters.branch and group_by_field != 'branch':
		query_filters["branch"] = filters.branch
	if filters.vehicle_workshop_division and group_by_field != 'vehicle_workshop_division':
		query_filters["vehicle_workshop_division"] = filters.vehicle_workshop_division
	if filters.applies_to_item_brand and group_by_field != 'applies_to_item_brand':
		query_filters["applies_to_item_brand"] = filters.applies_to_item_brand
	if filters.applies_to_vehicle and group_by_field != 'applies_to_vehicle':
		query_filters["applies_to_vehicle"] = filters.applies_to_vehicle
	if filters.item_group and group_by_field != 'item_group':
		query_filters["item_group"] = filters.item_group
	if filters.customer_group and group_by_field != 'customer_group':
		query_filters["customer_group"] = filters.customer_group

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
		dimension = d[group_by_field]
		if account not in opening:
			opening[account] = {}
		opening[account][dimension] = {
			'opening_debit': d.opening_debit or 0,
			'opening_credit': d.opening_credit or 0
		}
	return opening

def calculate_values_with_grouping(accounts, gl_entries_by_account, opening_balances, filters, company_currency,
								  dimension_values, group_by_field):
	init_values = {f"{field}_{dim}": 0.0 for field in value_fields for dim in dimension_values}
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
			d[f"opening_debit_{dim}"] = dim_opening.get("opening_debit", 0)
			d[f"opening_credit_{dim}"] = dim_opening.get("opening_credit", 0)

		for entry in gl_entries_by_account.get(d.name, []):
			if cstr(entry.is_opening) != "Yes":
				dim = entry[group_by_field]
				if dim in dimension_values:
					d[f"debit_{dim}"] += flt(entry.debit)
					d[f"credit_{dim}"] += flt(entry.credit)

		for dim in dimension_values:
			d[f"closing_debit_{dim}"] = d[f"opening_debit_{dim}"] + d[f"debit_{dim}"]
			d[f"closing_credit_{dim}"] = d[f"opening_credit_{dim}"] + d[f"credit_{dim}"]

		for dim in dimension_values:
			prepare_opening_closing_for_dimension(d, dim)

		for field_dim in init_values.keys():
			total_row[field_dim] += d[field_dim]

	return total_row

def prepare_opening_closing_for_dimension(row, dimension):
	dr_or_cr = "debit" if row["root_type"] in ["Asset", "Equity", "Expense"] else "credit"
	reverse_dr_or_cr = "credit" if dr_or_cr == "debit" else "debit"

	for col_type in ["opening", "closing"]:
		valid_col = f"{col_type}_{dr_or_cr}_{dimension}"
		reverse_col = f"{col_type}_{reverse_dr_or_cr}_{dimension}"
		row[valid_col] -= row[reverse_col]
		if row[valid_col] < 0:
			row[reverse_col] = abs(row[valid_col])
			row[valid_col] = 0.0
		else:
			row[reverse_col] = 0.0

def accumulate_values_into_parents_with_grouping(accounts, accounts_by_name, dimension_values):
	for d in reversed(accounts):
		if d.parent_account:
			parent = accounts_by_name[d.parent_account]
			for field in value_fields:
				for dim in dimension_values:
					key = f"{field}_{dim}"
					parent[key] += d[key]

def prepare_data_with_grouping(accounts, filters, total_row, parent_children_map, company_currency, dimension_values):
	data = []
	for d in accounts:
		if parent_children_map.get(d.account):
			for dim in dimension_values:
				prepare_opening_closing_for_dimension(d, dim)

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

		for field in value_fields:
			for dim in dimension_values:
				key = f"{field}_{dim}"
				row[key] = flt(d.get(key, 0.0), 3)
				if abs(row[key]) >= 0.005:
					has_value = True

		row["has_value"] = has_value
		data.append(row)

	data.extend([{}, total_row])
	return data

def get_opening_balances(filters):
	balance_sheet_opening = get_rootwise_opening_balances(filters, "Balance Sheet")
	pl_opening = get_rootwise_opening_balances(filters, "Profit and Loss")
	balance_sheet_opening.update(pl_opening)
	return balance_sheet_opening

def get_rootwise_opening_balances(filters, report_type):
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
				query_filters.update({dimension.fieldname: filters.get(dimension.fieldname)})

	hooks = frappe.get_hooks('set_gl_conditions')
	for method in hooks:
		frappe.get_attr(method)(filters, additional_conditions, alias="`tabGL Entry`")

	additional_conditions = " and {0}".format(" and ".join(additional_conditions)) if additional_conditions else ""

	gle = frappe.db.sql("""
		select
			account, sum(debit) as opening_debit, sum(credit) as opening_credit
		from `tabGL Entry`
		where
			company = %(company)s
			{additional_conditions}
			and (posting_date < %(from_date)s or is_opening = 'Yes')
			and account in (select name from `tabAccount` where report_type=%(report_type)s)
		group by account
	""".format(additional_conditions=additional_conditions), query_filters, as_dict=True)

	opening = frappe._dict()
	for d in gle:
		opening.setdefault(d.account, d)

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

def calculate_values(accounts, gl_entries_by_account, opening_balances, filters, company_currency):
	init = {
		"opening_debit": 0.0,
		"opening_credit": 0.0,
		"debit": 0.0,
		"credit": 0.0,
		"closing_debit": 0.0,
		"closing_credit": 0.0
	}

	total_row = {
		"account": "'" + _("Total") + "'",
		"account_name": "'" + _("Total") + "'",
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
	}

	for d in accounts:
		d.update(init.copy())
		d["opening_debit"] = opening_balances.get(d.name, {}).get("opening_debit", 0)
		d["opening_credit"] = opening_balances.get(d.name, {}).get("opening_credit", 0)

		for entry in gl_entries_by_account.get(d.name, []):
			if cstr(entry.is_opening) != "Yes":
				d["debit"] += flt(entry.debit)
				d["credit"] += flt(entry.credit)

		d["closing_debit"] = d["opening_debit"] + d["debit"]
		d["closing_credit"] = d["opening_credit"] + d["credit"]
		prepare_opening_closing(d)

		for field in value_fields:
			total_row[field] += d[field]

	return total_row

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

def prepare_data(accounts, filters, total_row, parent_children_map, company_currency):
	data = []
	for d in accounts:
		if parent_children_map.get(d.account):
			prepare_opening_closing(d)

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

		for key in value_fields:
			row[key] = flt(d.get(key, 0.0), 3)
			if abs(row[key]) >= 0.005:
				has_value = True

		row["has_value"] = has_value
		data.append(row)

	data.extend([{}, total_row])
	return data

def get_columns(filters=None, group_by_field=None, dimension_values=None):
	if not filters or not group_by_field or filters.group_by not in GROUP_BY_MAPPING:
		return [
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
			},
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

	field_labels = {
		"opening_debit": _("Opening (Dr)"),
		"opening_credit": _("Opening (Cr)"),
		"debit": _("Debit"),
		"credit": _("Credit"),
		"closing_debit": _("Closing (Dr)"),
		"closing_credit": _("Closing (Cr)")
	}

	for field in value_fields:
		for dim_value in dimension_values:
			columns.append({
				"fieldname": f"{field}_{dim_value}",
				"label": f"{field_labels[field]} {dim_value}",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120
			})

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