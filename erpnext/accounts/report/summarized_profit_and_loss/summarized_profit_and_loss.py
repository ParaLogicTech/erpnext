# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from erpnext.accounts.report.financial_statements import get_cost_centers_with_children
from frappe import _
from frappe.utils import getdate, get_first_day, add_years, get_year_start, flt, cint
from datetime import timedelta
from erpnext.accounts.doctype.budget.budget import get_accumulated_monthly_budget
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_all_dimension_fields,
	get_accounting_dimensions,
	get_dimension_with_children,
)
from erpnext import get_default_company


def execute(filters=None):
	return SummarizedProfitAndLossReport(filters).run()


class SummarizedProfitAndLossReport:
	gl_fields = [
		'mtd_actual', 'mtd_prev_year',
		'ytd_actual', 'ytd_prev_year',
	]
	budget_fields = [
		'mtd_budget', 'ytd_budget'
	]
	total_fields = gl_fields + budget_fields
	total_with_display_fields = total_fields + [f"{f}_display" for f in total_fields]

	def __init__(self, filters=None):
		self._account_group_docs = {}
		self.filters = frappe._dict(filters or {})

	def run(self):
		self.validate_filters()
		return self.get_columns(), self.get_data()

	def validate_filters(self):
		if not self.filters.company:
			self.filters.company = get_default_company()
		if not self.filters.company:
			frappe.throw(_("Company is mandatory"))

		self.filters.report_date = getdate(self.filters.report_date)
		self.filters.month_start_date = get_first_day(self.filters.report_date)
		self.filters.year_start_date = get_year_start(self.filters.report_date)

		self.filters.prev_year_date = add_years(self.filters.report_date, -1)
		self.filters.prev_year_month_start = add_years(self.filters.month_start_date, -1)
		self.filters.prev_year_start = add_years(self.filters.year_start_date, -1)

	def get_data(self):
		current_account_group = self.filters.get('account_group')
		is_root = False
		if not current_account_group:
			is_root = True
			current_account_group = frappe.db.get_value(
				"Account Group",
				{
					"company": self.filters.get('company'),
					"is_root_level": 1,
					"report_type": "Profit and Loss",
				},
				"name",
			)

			if not current_account_group:
				frappe.throw(_("Please configure Root Level Profit and Loss Account Group or filter by Account Group"))

		data = self.get_account_group_data(current_account_group)

		if not is_root:
			totals = {k: 0 for k in self.total_with_display_fields}
			for row in data:
				if row.get('row_type') in ['Account', 'Account Group']:
					for key in totals:
						totals[key] += flt(row.get(key))

			data.append(frappe._dict({
				'row_type': 'Total',
				'account_name': 'Total',
				'is_bold': 1,
				**totals
			}))

		return data

	def get_account_group_data(self, group_name):
		"""Aggregate account and group data for a given group."""
		data = []
		group = self.get_account_group_doc(group_name)
		group_root_type = group.root_type

		group_account_map = self.get_accounts_in_account_group(group)
		all_accounts = group_account_map[group.name]
		current_gl_data = self.get_gl_data(all_accounts, self.filters.year_start_date, self.filters.report_date)
		prev_year_gl_data = self.get_gl_data(all_accounts, self.filters.prev_year_start, self.filters.prev_year_date)
		raw_budget_records = self.get_budget_data(all_accounts, self.filters.report_date.year)
		budget_data = self.calculate_budget_totals(raw_budget_records)

		account_totals = self.get_account_totals(current_gl_data, prev_year_gl_data, budget_data)

		# Calculate Child Group Totals
		child_group_totals = {}
		for row in group.rows:
			if row.row_type != "Account Group":
				continue

			child_group_doc = self.get_account_group_doc(row.account_group)

			group_accounts = group_account_map.get(row.account_group) or set()
			group_totals = self.get_group_totals(group_accounts, account_totals)
			group_totals["root_type"] = child_group_doc.root_type

			child_group_totals[row.account_group] = group_totals

		# Build rows
		running_totals = {f: 0 for f in self.total_fields}

		for row in group.rows:
			if row.row_type == "Account":
				totals = account_totals.get(row.account) or {}
				data.append(self.get_row(row.row_type, row.account, totals=totals, group_root_type=group_root_type))

				for f in self.total_fields:
					running_totals[f] += flt(totals.get(f))

			elif row.row_type == "Account Group":
				totals = child_group_totals.get(row.account_group) or {}
				data.append(self.get_row(row.row_type, row.account_group, totals=totals, group_root_type=group_root_type))

				for f in self.total_fields:
					running_totals[f] += flt(totals.get(f))

			elif row.row_type == "Section Break":
				data.append(self.get_row(row.row_type, row.section_name, is_bold=True, group_root_type=group_root_type))

			elif row.row_type == "Section Group":
				section_totals = self.calculate_section_totals(row, child_group_totals, running_totals)
				data.append(self.get_row(row.row_type, row.section_name, totals=section_totals, is_bold=True, group_root_type=group_root_type))

		return data

	def get_accounts_in_account_group(self, account_group):
		account_map = {}

		self.get_accounts_in_child_account_group(account_group.name, account_group.name, account_map)
		for row in account_group.rows:
			if row.row_type == "Account Group":
				self.get_accounts_in_child_account_group(row.account_group, row.account_group, account_map)

		return account_map

	def get_accounts_in_child_account_group(self, current_group_name, root_group_name, account_map):
		current_group = self.get_account_group_doc(current_group_name)

		for row in current_group.rows:
			if row.row_type == "Account":
				account_map.setdefault(root_group_name, set()).add(row.account)
			elif row.row_type == "Account Group":
				self.get_accounts_in_child_account_group(row.account_group, root_group_name, account_map)

	def get_gl_data(self, accounts, from_date, to_date):
		dimension_conditions, dimension_args = self.get_dimension_conditions()

		args = {
			"accounts": accounts,
			"from_date": from_date,
			"to_date": to_date,
			**dimension_args,
		}

		return frappe.db.sql(f"""
			SELECT posting_date, account, credit, debit
			FROM `tabGL Entry`
			WHERE
				account in %(accounts)s
				and posting_date between %(from_date)s and %(to_date)s
				{dimension_conditions}
			ORDER BY posting_date
		""", args, as_dict=1)

	def get_dimension_conditions(self):
		dimension_conditions = []
		args = {}

		if self.filters.get("cost_center"):
			args["cost_center"] = get_cost_centers_with_children(self.filters.cost_center)
			dimension_conditions.append("cost_center in %(cost_center)s")

		accounting_dimensions = get_accounting_dimensions(as_list=False)
		for dimension in accounting_dimensions:
			if self.filters.get(dimension.fieldname):
				if frappe.get_cached_value('DocType', dimension.document_type, 'is_tree'):
					args[dimension.fieldname] = get_dimension_with_children(dimension.document_type, self.filters.get(dimension.fieldname))
					dimension_conditions.append("{0} in %({0})s".format(dimension.fieldname))
				else:
					args[dimension.fieldname] = self.filters.get(dimension.fieldname)
					dimension_conditions.append("{0} = %({0})s".format(dimension.fieldname))

		dimension_conditions = " AND " + " AND ".join(dimension_conditions) if dimension_conditions else ""

		return dimension_conditions, args

	def get_account_totals(self, current_gl_data, prev_year_gl_data, budget_data):
		template = frappe._dict({f: 0 for f in self.gl_fields + self.budget_fields})

		account_totals = {}
		for d in current_gl_data:
			if self.filters.month_start_date <= d.posting_date <= self.filters.report_date:
				group = account_totals.setdefault(d.account, template.copy())
				group["mtd_actual"] += d.credit - d.debit
			if self.filters.year_start_date <= d.posting_date <= self.filters.report_date:
				group = account_totals.setdefault(d.account, template.copy())
				group["ytd_actual"] += d.credit - d.debit

		for d in prev_year_gl_data:
			if self.filters.prev_year_month_start <= d.posting_date <= self.filters.prev_year_date:
				group = account_totals.setdefault(d.account, template.copy())
				group["mtd_prev_year"] += d.credit - d.debit
			if self.filters.prev_year_start <= d.posting_date <= self.filters.prev_year_date:
				group = account_totals.setdefault(d.account, template.copy())
				group["ytd_prev_year"] += d.credit - d.debit

		# --- Integrate budget data
		for account, budget in budget_data.items():
			group = account_totals.setdefault(account, template.copy())
			group["mtd_budget"] = budget.get("mtd_budget", 0)
			group["ytd_budget"] = budget.get("ytd_budget", 0)

		return account_totals

	def get_group_totals(self, group_accounts, account_totals):
		group_totals = frappe._dict({f: 0 for f in self.total_fields})

		for account in group_accounts:
			totals = account_totals.get(account)
			if not totals:
				continue

			for f in self.total_fields:
				group_totals[f] += flt(totals.get(f))

		return group_totals

	def get_row(self, row_type, row_value, totals=None, is_bold=False, group_root_type=None):
		row = frappe._dict()

		no_values = True
		if totals is not None:
			no_values = False

		if not no_values:
			for f in self.total_fields:
				row[f] = 0

		if not totals:
			totals = frappe._dict()

		row.update(totals)

		row["row_type"] = row_type
		row["account_name"] = row_value or ""
		row["root_type"] = totals.get("root_type") or group_root_type
		row["is_bold"] = cint(is_bold)

		if not no_values:
			multiplier = -1 if row["root_type"] == "Expense" else 1
			for f in self.total_fields:
				row[f"{f}_display"] = row[f] * multiplier

		return row

	def calculate_section_totals(self, row, child_groups, running_totals):
		if not row.section_account_groups:
			return running_totals.copy()

		included_groups = []
		included_categories = set()

		for line in row.section_account_groups.split('\n'):
			group_code = line.strip()
			if group_code and group_code in child_groups:
				group_info = child_groups[group_code]
				included_groups.append(group_info)
				included_categories.add(group_info["root_type"])

		section_totals = {key: 0 for key in self.total_fields}
		for group_info in included_groups:
			for key in section_totals:
				section_totals[key] += flt(group_info.get(key))

		if len(included_categories) == 1:
			section_totals["root_type"] = list(included_categories)[0]

		return section_totals


	def add_dimension_filters(self, table_alias, conditions, params):
		"""Helper to add dimension filters, including subtree filtering for tree dimensions."""
		for dim in get_all_dimension_fields():
			filter_value = self.filters.get(dim)
			if not filter_value:
				continue

			table = "Budget" if table_alias == "b" else "GL Entry"
			if not frappe.db.has_column(table, dim):
				continue

			doctype = frappe.db.get_value("Custom Field", {"dt": table, "fieldname": dim}, "options") or dim.replace("_", " ").title()
			is_tree = frappe.get_cached_value("DocType", doctype, "is_tree") or False
			col = f"{table_alias}.{dim}" if table_alias else dim
			values = [v for v in (filter_value if isinstance(filter_value, (list, tuple, set)) else [filter_value]) if v]

			if not values:
				continue

			if is_tree:
				values = self.get_tree_descendants(doctype, values)

			if values:
				placeholders = ', '.join(['%s'] * len(values))
				conditions.append(f"{col} IN ({placeholders})")
				params.extend(values)

	def get_tree_descendants(self, doctype, parent_names):
		"""Get descendants for tree DocType nodes"""
		if not parent_names:
			return []

		parent_data = frappe.get_all(doctype,
			filters={'name': ['in', parent_names]},
			fields=['lft', 'rgt'],
			order_by='lft'
		)
		if not parent_data:
			return []

		or_filters = []
		args = []
		for p in parent_data:
			or_filters.append("(lft >= %s AND rgt <= %s)")
			args.extend([p.lft, p.rgt])

		return [d.name for d in frappe.db.sql(
			f"""SELECT name FROM `tab{doctype}` WHERE {" OR ".join(or_filters)}""",
			args, as_dict=1
		)]

	def get_columns(self):
		return [
			{
				"fieldname": "account_name",
				"label": _("Account"),
				"fieldtype": "Data",
				"width": 300
			},
			{
				"fieldname": "mtd_actual_display",
				"label": _("M.T.D Actual"),
				"fieldtype": "Currency",
				"width": 150
			},
			{
				"fieldname": "mtd_budget_display",
				"label": _("M.T.D Budget"),
				"fieldtype": "Currency",
				"width": 150
			},
			{
				"fieldname": "mtd_prev_year_display",
				"label": _("M.T.D Previous Year"),
				"fieldtype": "Currency",
				"width": 150
			},
			{
				"fieldname": "ytd_actual_display",
				"label": _("Y.T.D Actual"),
				"fieldtype": "Currency",
				"width": 150
			},
			{
				"fieldname": "ytd_budget_display",
				"label": _("Y.T.D Budget"),
				"fieldtype": "Currency",
				"width": 150
			},
			{
				"fieldname": "ytd_prev_year_display",
				"label": _("Y.T.D Previous Year"),
				"fieldtype": "Currency",
				"width": 150
			}
		]

	def get_account_group_doc(self, group_name):
		if not self._account_group_docs.get(group_name):
			self._account_group_docs[group_name] = frappe.get_doc("Account Group", group_name)

		return self._account_group_docs[group_name]

	def get_budget_data(self, accounts, fiscal_year):
		"""Fetch raw budget records for all accounts in bulk for the fiscal year"""
  
		if not accounts:
			return []

		accounts = list(accounts)
  
		return frappe.db.sql("""
			SELECT ba.account, ba.budget_amount, b.monthly_distribution
			FROM `tabBudget Account` ba
			INNER JOIN `tabBudget` b ON ba.parent = b.name
			WHERE ba.account IN %(accounts)s
			AND b.fiscal_year = %(fiscal_year)s
			AND b.docstatus = 1
		""", {
			"accounts": accounts,
			"fiscal_year": fiscal_year
		}, as_dict=1)

	def calculate_budget_totals(self, budget_records):
		"""Calculate MTD and YTD budget for each account from raw budget records"""
  
		budget_data = {}
  
		fy_start, fy_end = frappe.db.get_value('Fiscal Year', self.filters.report_date.year, ['year_start_date', 'year_end_date'])

		for row in budget_records:
			account = row.account
			budget = row.budget_amount or 0
			monthly_distribution = row.monthly_distribution

			# MTD Budget
			if monthly_distribution:
				if self.filters.month_start_date > fy_start:
					mtd_budget = (
						get_accumulated_monthly_budget(monthly_distribution, self.filters.report_date, self.filters.report_date.year, budget)
						- get_accumulated_monthly_budget(monthly_distribution, self.filters.month_start_date - timedelta(days=1), self.filters.report_date.year, budget)
					)
				else:
					mtd_budget = get_accumulated_monthly_budget(monthly_distribution, self.filters.report_date, self.filters.report_date.year, budget)
			else:
				days_in_period = (self.filters.report_date - self.filters.month_start_date).days + 1
				days_in_year = (fy_end - fy_start).days + 1 if fy_start and fy_end else 365
				mtd_budget = (budget * days_in_period / days_in_year)

			# YTD Budget
			if monthly_distribution:
				if self.filters.year_start_date > fy_start:
					ytd_budget = (
						get_accumulated_monthly_budget(monthly_distribution, self.filters.report_date, self.filters.report_date.year, budget)
						- get_accumulated_monthly_budget(monthly_distribution, self.filters.year_start_date - timedelta(days=1), self.filters.report_date.year, budget)
					)
				else:
					ytd_budget = get_accumulated_monthly_budget(monthly_distribution, self.filters.report_date, self.filters.report_date.year, budget)
			else:
				days_in_period = (self.filters.report_date - self.filters.year_start_date).days + 1
				days_in_year = (fy_end - fy_start).days + 1 if fy_start and fy_end else 365
				ytd_budget = (budget * days_in_period / days_in_year)

			budget_data[account] = {
				"mtd_budget": mtd_budget,
				"ytd_budget": ytd_budget
			}

		return budget_data
