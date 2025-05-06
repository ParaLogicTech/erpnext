# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, get_first_day, add_years, get_year_start
from datetime import timedelta
from erpnext.accounts.doctype.budget.budget import get_accumulated_monthly_budget
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_all_dimension_fields


def execute(filters=None):
	return SummarizedProfitAndLossReport(filters).run()


class SummarizedProfitAndLossReport:
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})

	def run(self):
		self.validate_filters()
		return self.get_columns(), self.get_data()

	def validate_filters(self):
		self.filters.report_date = getdate(self.filters.report_date)
		self.filters.month_start_date = get_first_day(self.filters.report_date)
		self.filters.year_start_date = get_year_start(self.filters.report_date)

		self.filters.prev_year_date = add_years(self.filters.report_date, -1)
		self.filters.prev_year_month_start = add_years(self.filters.month_start_date, -1)
		self.filters.prev_year_start = add_years(self.filters.year_start_date, -1)

	def get_data(self):
		dates = {
			'report_date': self.filters.report_date,
			'month_start': self.filters.month_start_date,
			'year_start': self.filters.year_start_date,
			'prev_year_date': self.filters.prev_year_date,
			'prev_year_month_start': self.filters.prev_year_month_start,
			'prev_year_start': self.filters.prev_year_start,
		}

		if self.filters.get('account_group'):
			data = self.get_account_group_data(
				self.filters.get('account_group'),
				self.filters.get('company'),
				**dates
			)

			# Add total row when filtered
			totals = {
				'mtd_actual': 0, 'mtd_budget': 0, 'mtd_prev_year': 0,
				'ytd_actual': 0, 'ytd_budget': 0, 'ytd_prev_year': 0
			}

			for row in data:
				if row.get('row_type') in ['Account', 'Account Group']:
					for key in totals:
						totals[key] += row.get(key, 0)

			data.append({
				'row_type': 'Total',
				'account_name': 'Total',
				'is_bold': 1,
				**totals
			})

			return data
		else:
			root_group = frappe.db.get_value(
				"Account Group",
				{
					"company": self.filters.get('company'),
					"is_root_level": 1,
					"reporting_type": "Profit and Loss"
				},
				["name", "group_name"]
			)

			if not root_group:
				frappe.msgprint("No root level Profit and Loss group defined for this Company. Please create one first.")
				return []

			data = self.get_account_group_data(
				root_group[0],
				self.filters.get('company'),
				**dates
			)

			for row in data:
				if row.get('row_type') == 'Account Group':
					row['account_group'] = row.get('account_group') or row.get('name')

			return data

	def get_account_group_data(
		self,
		group_name,
		company,
		report_date,
		month_start,
		year_start,
		prev_year_date,
		prev_year_month_start,
		prev_year_start
	):
		data = []
		group = frappe.get_doc("Account Group", group_name)
		running_totals = {k: 0 for k in ['mtd_actual', 'mtd_budget', 'mtd_prev_year',
			'ytd_actual', 'ytd_budget', 'ytd_prev_year']}

		# Preload child group data
		child_groups = {}

		for row in group.rows:
			if row.row_type == "Account Group":
				child_group = frappe.get_doc("Account Group", row.account_group)

				# Recursively calculate totals for child groups
				child_totals = self.calculate_group_totals(
					child_group, company, report_date, month_start, year_start,
					prev_year_date, prev_year_month_start, prev_year_start
				)

				child_groups[row.account_group] = {
					"name": row.account_group,
					"group_name": child_group.group_name,
					"totals": child_totals,
					"root_type": child_group.root_type
				}

		for row in group.rows:
			if row.row_type == "Account":
				# Get individual account balances
				account_data = self.get_account_balances(
					row.account, company, report_date, month_start, year_start,
					prev_year_date, prev_year_month_start, prev_year_start
				)

				data.append(account_data)

				for key in running_totals:
					running_totals[key] += account_data.get(key, 0)

			elif row.row_type == "Account Group":
				# Use preloaded child group data
				child_info = child_groups[row.account_group]

				data.append({
					"row_type": "Account Group",
					"account_name": child_info["group_name"],
					"account_group": child_info["name"],
					**child_info["totals"]
				})

				for key in running_totals:
					running_totals[key] += child_info["totals"][key]

			elif row.row_type == "Section Break":
				running_totals = {key: 0 for key in running_totals}

				data.append({
					"row_type": "Section Break",
					"account_name": row.section_name or "",
					"is_bold": 1
				})

			elif row.row_type == "Section Group":
				section_totals = self.calculate_section_totals(row, child_groups, running_totals)
				data.append({
					"row_type": "Section Group",
					"account_name": row.section_name,
					"is_bold": 1,
					**section_totals
				})
				running_totals = {key: 0 for key in running_totals}

		return data

	def calculate_section_totals(self, row, child_groups, running_totals):
		if not row.section_account_groups:
			return running_totals.copy()

		section_totals = {key: 0 for key in running_totals}
		included_groups = []
		included_categories = set()

		for line in row.section_account_groups.split('\n'):
			if line.strip():
				group_code = line.strip().split('(')[-1].rstrip(')')
				if group_code and group_code in child_groups:
					group_info = child_groups[group_code]
					included_groups.append(group_info)
					included_categories.add(group_info["root_type"])

		if included_categories == {"Income"} or included_categories == {"Expense"}:
			for group_info in included_groups:
				for key in section_totals:
					section_totals[key] += group_info["totals"][key]
		else:
			income_totals = {key: 0 for key in running_totals}
			expense_totals = {key: 0 for key in running_totals}

			for group_info in included_groups:
				target_dict = income_totals if group_info["root_type"] == "Income" else expense_totals
				for key in target_dict:
					target_dict[key] += group_info["totals"][key]

			for key in section_totals:
				section_totals[key] = income_totals[key] - expense_totals[key]

		return section_totals

	def calculate_group_totals(self, group, company, report_date, month_start, year_start,
			prev_year_date, prev_year_month_start, prev_year_start):
		totals = {key: 0 for key in ['mtd_actual', 'mtd_budget', 'mtd_prev_year',
			'ytd_actual', 'ytd_budget', 'ytd_prev_year']}

		accounts = frappe.db.sql("""
			WITH RECURSIVE cte AS (
				SELECT a.name, a.account_type
				FROM `tabAccount` a
				INNER JOIN `tabAccount Group Row` agr ON agr.account = a.name
				WHERE agr.parent = %s AND agr.row_type = 'Account'
				UNION ALL
				SELECT a.name, a.account_type
				FROM `tabAccount` a
				INNER JOIN `tabAccount Group Row` agr ON agr.account = a.name
				INNER JOIN `tabAccount Group` ag ON agr.parent = ag.name
				INNER JOIN `tabAccount Group Row` pagr ON pagr.account_group = ag.name
				WHERE pagr.parent = %s AND agr.row_type = 'Account'
			)
			SELECT name, account_type FROM cte
		""", (group.name, group.name), as_dict=1)

		# Calculate totals for each account
		for account in accounts:
			account_data = self.get_account_balances(
				account.name, company, report_date, month_start, year_start,
				prev_year_date, prev_year_month_start, prev_year_start
			)

			for key in totals:
				totals[key] += account_data.get(key, 0)

		return totals

	def get_account_balances(self, account, company, report_date, month_start, year_start,
			prev_year_date, prev_year_month_start, prev_year_start):
		"""Get account balances with sign based on Account Group's root type."""
		account_doc = frappe.get_doc("Account", account)
		
		# Get Account Group's root type
		group_root_type = frappe.get_value(
			"Account Group",
			frappe.get_value("Account Group Row", {"account": account}, "parent"),
			"root_type"
		)

		# Get all balances
		balances = {
			"mtd_actual": self.get_balance(account, company, month_start, report_date, account_doc),
			"ytd_actual": self.get_balance(account, company, year_start, report_date, account_doc),
			"mtd_prev_year": self.get_balance(account, company, prev_year_month_start, prev_year_date, account_doc),
			"ytd_prev_year": self.get_balance(account, company, prev_year_start, prev_year_date, account_doc),
			"mtd_budget": self.get_budget_amount(account, company, month_start, report_date, year_start, report_date.year),
			"ytd_budget": self.get_budget_amount(account, company, year_start, report_date, year_start, report_date.year)
		}

		# Apply sign based on group type (positive for Income, negative for Expense)
		multiplier = 1 if group_root_type == "Income" else -1
		signed_balances = {k: abs(v) * multiplier for k, v in balances.items()}

		return {
			"row_type": "Account",
			"account_name": f"{account_doc.account_number} - {account_doc.account_name}" if account_doc.account_number else account_doc.account_name,
			"account": account,
			"account_type": account_doc.account_type,
			**signed_balances
		}

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

	def get_balance(self, account, company, start_date, end_date, account_doc):
		"""Get GL balance for the account between given dates, filtered by dimensions."""
		conditions = [
			"account=%s",
			"company=%s",
			"posting_date BETWEEN %s AND %s",
			"docstatus = 1"
		]
		params = [account, company, start_date, end_date]
		self.add_dimension_filters('', conditions, params)
		where_clause = " AND ".join(conditions)
		balance = frappe.db.sql(f"""
			SELECT SUM(debit) - SUM(credit)
			FROM `tabGL Entry`
			WHERE {where_clause}
		""", tuple(params))[0][0] or 0
		return balance

	def get_budget_amount(self, account, company, start_date, end_date, year_start, fiscal_year):
		"""Get budget amount for the account between given dates, filtered by company, fiscal year, account, and parent Budget dimensions."""
		conditions = [
			"ba.account = %s",
			"b.company = %s",
			"b.fiscal_year = %s",
			"b.docstatus = 1"
		]
		params = [account, company, fiscal_year]
		self.add_dimension_filters('b', conditions, params)
		where_clause = " AND ".join(conditions)
		budget_data = frappe.db.sql(f"""
			SELECT ba.budget_amount, b.monthly_distribution
			FROM `tabBudget Account` ba
			INNER JOIN `tabBudget` b ON ba.parent = b.name
			WHERE {where_clause}
		""", tuple(params), as_dict=1)
		total_budget = 0
		for row in budget_data:
			budget = row.budget_amount or 0
			monthly_distribution = row.monthly_distribution
			if monthly_distribution:
				if start_date > year_start:
					total_budget += (
						get_accumulated_monthly_budget(monthly_distribution, end_date, fiscal_year, budget)
						- get_accumulated_monthly_budget(monthly_distribution, start_date - timedelta(days=1), fiscal_year, budget)
					)
				else:
					total_budget += get_accumulated_monthly_budget(monthly_distribution, end_date, fiscal_year, budget)
			else:
				fy_start, fy_end = frappe.db.get_value('Fiscal Year', fiscal_year, ['year_start_date', 'year_end_date'])
				days_in_period = (end_date - start_date).days + 1
				days_in_year = (fy_end - fy_start).days + 1 if fy_start and fy_end else 365
				total_budget += (budget * days_in_period / days_in_year)
		return total_budget

	def get_columns(self):
		return [
			{
				"fieldname": "account_name",
				"label": _("Account"),
				"fieldtype": "Data",
				"width": 300
			},
			{
				"fieldname": "mtd_actual",
				"label": _("M.T.D Actual"),
				"fieldtype": "Currency",
				"width": 150
			},
			{
				"fieldname": "mtd_budget",
				"label": _("M.T.D Budget"),
				"fieldtype": "Currency",
				"width": 150
			},
			{
				"fieldname": "mtd_prev_year",
				"label": _("M.T.D Previous Year"),
				"fieldtype": "Currency",
				"width": 150
			},
			{
				"fieldname": "ytd_actual",
				"label": _("Y.T.D Actual"),
				"fieldtype": "Currency",
				"width": 150
			},
			{
				"fieldname": "ytd_budget",
				"label": _("Y.T.D Budget"),
				"fieldtype": "Currency",
				"width": 150
			},
			{
				"fieldname": "ytd_prev_year",
				"label": _("Y.T.D Previous Year"),
				"fieldtype": "Currency",
				"width": 150
			}
		]
