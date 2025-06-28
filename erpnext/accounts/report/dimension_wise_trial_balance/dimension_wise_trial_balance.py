# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe, erpnext
from frappe import _
from frappe.utils import flt, getdate, formatdate, cstr
from erpnext.accounts.report.financial_statements import filter_accounts
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions, \
	get_dimension_with_children
from collections import defaultdict

value_fields = ("opening_debit", "opening_credit", "debit", "credit", "closing_debit", "closing_credit")


def execute(filters=None):
	validate_filters(filters)
	based_on_field = get_based_on_field(filters.get("based_on")) if filters.get("based_on") else None

	if not based_on_field:
		frappe.throw(_("Invalid Based On selection"))

	data = get_data(filters, based_on_field)
	columns = get_columns(filters, based_on_field, data.get('dimension_values', []), data.get('dimension_labels', []))
	return columns, data.get('report_data', [])


def get_based_on_field(based_on_value):
	"""Get the field name from the based on value dynamically"""
	if not based_on_value:
		return None

	if based_on_value == "Cost Center":
		return "cost_center"
	elif based_on_value == "Project":
		return "project"

	accounting_dimensions = get_accounting_dimensions(as_list=False)
	for dimension in accounting_dimensions:
		if dimension.document_type == based_on_value:
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


class GLDataProcessor:
	"""Handles all GL Entry data processing with single query optimization"""

	def __init__(self, filters, based_on_field):
		self.filters = filters
		self.based_on_field = based_on_field
		self.company_currency = erpnext.get_company_currency(filters.company)

	def build_conditions_and_filters(self):
		"""Build SQL conditions and query filters once"""
		conditions = []
		query_filters = {
			"company": self.filters.company,
			"from_date": self.filters.from_date,
			"to_date": self.filters.to_date,
			"year_start_date": self.filters.year_start_date
		}

		if not flt(self.filters.with_period_closing_entry):
			conditions.append("voucher_type != 'Period Closing Voucher'")

		if self.filters.cost_center:
			cost_center_data = frappe.db.get_value('Cost Center', self.filters.cost_center, 'lft, rgt')
			if cost_center_data:
				lft, rgt = cost_center_data
				conditions.append(f"cost_center in (select name from `tabCost Center` where lft >= {lft} and rgt <= {rgt} and disabled = 0)")

		if self.filters.project:
			conditions.append("project = %(project)s")
			query_filters["project"] = self.filters.project

		accounting_dimensions = get_accounting_dimensions(as_list=False)
		if accounting_dimensions:
			for dimension in accounting_dimensions:
				if self.filters.get(dimension.fieldname):
					if self.based_on_field == dimension.fieldname:
						conditions.append(f"{dimension.fieldname} = %({dimension.fieldname})s")
						query_filters[dimension.fieldname] = self.filters.get(dimension.fieldname)
					else:
						if frappe.get_cached_value('DocType', dimension.document_type, 'is_tree'):
							dimension_values = get_dimension_with_children(dimension.document_type, self.filters.get(dimension.fieldname))
							conditions.append(f"{dimension.fieldname} in %({dimension.fieldname})s")
							query_filters[dimension.fieldname] = dimension_values
						else:
							conditions.append(f"{dimension.fieldname} = %({dimension.fieldname})s")
							query_filters[dimension.fieldname] = self.filters.get(dimension.fieldname)

		if self.filters.finance_book:
			query_filters["finance_book"] = self.filters.finance_book
			query_filters["company_fb"] = frappe.db.get_value("Company", self.filters.company, 'default_finance_book')

			if self.filters.include_default_book_entries:
				conditions.append("(finance_book in (%(finance_book)s, %(company_fb)s, '') OR finance_book IS NULL)")
			else:
				conditions.append("finance_book = %(finance_book)s")

		return conditions, query_filters

	def get_all_gl_data(self):
		"""Single optimized query to get all GL data with opening and period balances"""
		conditions, query_filters = self.build_conditions_and_filters()

		min_lft, max_rgt = frappe.db.sql("""
			select min(lft), max(rgt)
			from `tabAccount`
			where company = %s
		""", (self.filters.company,))[0]

		conditions_str = " AND " + " AND ".join(conditions) if conditions else ""

		if self.based_on_field == 'cost_center':
			dimension_select = f"cc.cost_center_name as dimension_label, gle.{self.based_on_field} as dimension_value"
			dimension_join = "INNER JOIN `tabCost Center` cc ON gle.cost_center = cc.name AND cc.disabled = 0"
		elif self.based_on_field == 'project':
			dimension_select = f"gle.{self.based_on_field} as dimension_label, gle.{self.based_on_field} as dimension_value"
			dimension_join = ""
		else:
			dimension_select = f"gle.{self.based_on_field} as dimension_label, gle.{self.based_on_field} as dimension_value"
			dimension_join = ""

		sql = f"""SELECT account,{dimension_select},
			SUM(CASE WHEN posting_date < %(from_date)s OR is_opening = 'Yes' THEN debit ELSE 0 END) as opening_debit,
			SUM(CASE WHEN posting_date < %(from_date)s OR is_opening = 'Yes' THEN credit ELSE 0 END) as opening_credit,
			SUM(CASE WHEN posting_date BETWEEN %(from_date)s AND %(to_date)s AND is_opening != 'Yes' THEN debit ELSE 0 END) as period_debit,
			SUM(CASE WHEN posting_date BETWEEN %(from_date)s AND %(to_date)s AND is_opening != 'Yes' THEN credit ELSE 0 END) as period_credit,
		acc.report_type
		FROM `tabGL Entry` gle
		INNER JOIN `tabAccount` acc ON gle.account = acc.name
		{dimension_join}
		WHERE gle.company = %(company)s
			AND gle.account IN (
				SELECT name FROM `tabAccount` 
				WHERE lft >= {min_lft} AND rgt <= {max_rgt} AND company = %(company)s
			)
			AND gle.{self.based_on_field} IS NOT NULL 
			AND gle.{self.based_on_field} != ''
			AND (
				posting_date < %(from_date)s 
				OR (posting_date BETWEEN %(from_date)s AND %(to_date)s)
				OR is_opening = 'Yes'
			)
			{conditions_str}
		GROUP BY account, gle.{self.based_on_field}, acc.report_type
		ORDER BY account, gle.{self.based_on_field}
		"""

		return frappe.db.sql(sql, query_filters, as_dict=True)

	def process_gl_data(self, gl_entries):
		"""Process GL entries into structured data"""
		account_data = defaultdict(lambda: defaultdict(dict))
		dimension_values = set()
		dimension_labels = {}

		for entry in gl_entries:
			account = entry.account
			dim_value = entry.dimension_value
			dim_label = entry.dimension_label

			dimension_values.add(dim_value)
			dimension_labels[dim_value] = dim_label

			opening_debit = entry.opening_debit or 0
			opening_credit = entry.opening_credit or 0

			if entry.report_type == "Profit and Loss" and not self.filters.show_unclosed_fy_pl_balances:
				opening_debit = 0
				opening_credit = 0

			account_data[account][dim_value] = {
				'opening_debit': opening_debit,
				'opening_credit': opening_credit,
				'period_debit': entry.period_debit or 0,
				'period_credit': entry.period_credit or 0,
			}

		return account_data, sorted(dimension_values), dimension_labels


def get_data(filters, based_on_field):
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

	gl_data_processor = GLDataProcessor(filters, based_on_field)
	gl_entries = gl_data_processor.get_all_gl_data()
	account_data, dimension_values, dimension_labels = gl_data_processor.process_gl_data(gl_entries)

	total_row = calculate_account_values(accounts, account_data, dimension_values, company_currency)

	accumulate_values_into_parents(accounts, accounts_by_name, dimension_values)

	data = prepare_data(accounts, filters, total_row, parent_children_map, company_currency, dimension_values)

	if not filters.get("show_zero_values"):
		data = [row for row in data if row.get("has_value", True)]

	set_zero_for_group_accounts(data, parent_children_map, dimension_values)

	return {
		"report_data": data,
		"dimension_values": dimension_values,
		"dimension_labels": dimension_labels
	}


def calculate_account_values(accounts, account_data, dimension_values, company_currency):
	"""Calculate opening, movement, and closing values for each account and dimension"""
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
		for dim in dimension_values:
			account[f"opening_{dim}"] = 0.0
			account[f"movement_{dim}"] = 0.0
			account[f"closing_{dim}"] = 0.0

		# Calculate values for each dimension
		account_gl_data = account_data.get(account.name, {})

		for dim in dimension_values:
			dim_data = account_gl_data.get(dim, {})

			opening_debit = dim_data.get('opening_debit', 0)
			opening_credit = dim_data.get('opening_credit', 0)
			account[f"opening_{dim}"] = opening_debit - opening_credit

			period_debit = dim_data.get('period_debit', 0)
			period_credit = dim_data.get('period_credit', 0)
			account[f"movement_{dim}"] = period_debit - period_credit

			account[f"closing_{dim}"] = account[f"opening_{dim}"] + account[f"movement_{dim}"]

			total_row[f"opening_{dim}"] += account[f"opening_{dim}"]
			total_row[f"movement_{dim}"] += account[f"movement_{dim}"]
			total_row[f"closing_{dim}"] += account[f"closing_{dim}"]

	return total_row


def accumulate_values_into_parents(accounts, accounts_by_name, dimension_values):
	"""Accumulate child values into parent accounts"""
	for account in reversed(accounts):
		if account.parent_account and account.parent_account in accounts_by_name:
			parent = accounts_by_name[account.parent_account]
			for field_type in ["opening", "movement", "closing"]:
				for dim in dimension_values:
					key = f"{field_type}_{dim}"
					parent[key] = parent.get(key, 0) + account.get(key, 0)


def prepare_data(accounts, filters, total_row, parent_children_map, company_currency, dimension_values):
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
			"account_name": (f'{account.account_number} - {account.account_name}'
			if account.account_number else account.account_name)
		}

		# Add dimension values
		for field_type in ["opening", "movement", "closing"]:
			for dim in dimension_values:
				key = f"{field_type}_{dim}"
				row[key] = flt(account.get(key, 0.0), 3)
				if abs(row[key]) >= 0.005:
					has_value = True

		row["has_value"] = has_value
		data.append(row)

	data.extend([{}, total_row])
	return data


def set_zero_for_group_accounts(data, parent_children_map, dimension_values):
	"""Hide parent account totals for grouped reports while keeping structure visible"""
	for row in data:
		if row.get('account') and parent_children_map.get(row['account']):
			# This is a parent account, hide its totals
			for field_type in ["opening", "movement", "closing"]:
				for dim in dimension_values:
					key = f"{field_type}_{dim}"
					if key in row:
						del row[key]


def get_columns(filters=None, based_on_field=None, dimension_values=None, dimension_labels=None):
	"""Generate report columns"""
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

	# Add columns for each dimension - grouped by type
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