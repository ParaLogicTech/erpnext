# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, get_first_day, add_years, get_year_start
from datetime import timedelta
from erpnext.accounts.doctype.budget.budget import get_accumulated_monthly_budget
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_all_dimension_fields
import copy


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
		group_filter = self.filters.get('account_group')
		root_group = frappe.db.get_value(
			"Account Group",
			{
				"company": self.filters.get('company'),
				"is_root_level": 1,
				"reporting_type": "Profit and Loss"
			},
			["name", "root_type"]
		)
		report_root_type = root_group[1] if root_group else None

		if group_filter:
			data, raw_data = self.get_account_group_data(
				group_filter,
				self.filters.get('company'),
				report_root_type=report_root_type,
				**dates
			)

			totals = {k: 0 for k in ['mtd_actual', 'mtd_budget', 'mtd_prev_year',
									 'ytd_actual', 'ytd_budget', 'ytd_prev_year']}
			for row in raw_data:
				if row.get('row_type') in ['Account', 'Account Group']:
					for key in totals:
						totals[key] += row.get(key, 0)
			group_root_type = next((row.get('root_type') for row in raw_data
									if row.get('row_type') == 'Account Group' and row.get('account_group') == group_filter),
								   frappe.get_doc("Account Group", group_filter).root_type)
			
			##flip sign for display of totals
			for key in totals:
				totals[key] = self.flip_sign_for_display(totals[key], group_root_type)

			data.append({
				'row_type': 'Total',
				'account_name': 'Total',
				'is_bold': 1,
				**totals
			})

			return data
		else:
			data, _ = self.get_account_group_data(
				root_group[0],
				self.filters.get('company'),
				report_root_type=report_root_type,
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
		prev_year_start,
		report_root_type=None
	):
		"""Aggregate account and group data for a given group."""
		data = []
		group = frappe.get_doc("Account Group", group_name)

		running_totals = {key: 0 for key in [
			'mtd_actual', 'mtd_budget', 'mtd_prev_year',
			'ytd_actual', 'ytd_budget', 'ytd_prev_year']}


		# Preload child group data
		
		# Preload child group data
		child_groups = {}

		# Preload child group data
		for group_row in group.rows:
			if group_row.row_type == "Account Group":
				child_group_doc = frappe.get_doc("Account Group", group_row.account_group)
				child_totals = self.calculate_group_totals(
					child_group_doc, company, report_date, month_start, year_start,
					prev_year_date, prev_year_month_start, prev_year_start
				)
				child_groups[group_row.account_group] = {
					"name": group_row.account_group,
					"group_name": child_group_doc.group_name,
					"totals": child_totals,
					"root_type": child_group_doc.root_type
				}

		for group_row in group.rows:
			if group_row.row_type == "Account":
				account_data = self.get_account_balances(
					group_row.account, company, report_date, month_start, year_start,
					prev_year_date, prev_year_month_start, prev_year_start
				)
				data.append(account_data)

				for key in running_totals:
					running_totals[key] += account_data.get(key, 0)

			elif group_row.row_type == "Account Group":
				child_info = child_groups[group_row.account_group]
				data.append({
					"row_type": "Account Group",
					"account_name": child_info["group_name"],
					"account_group": child_info["name"],
					"root_type": child_info["root_type"],
					**child_info["totals"]
				})

				for key in running_totals:
					running_totals[key] += child_info["totals"][key]

			elif group_row.row_type == "Section Break":
				running_totals = {key: 0 for key in running_totals}
				data.append({
					"row_type": "Section Break",
					"account_name": group_row.section_name or "",
					"is_bold": 1
				})

			elif group_row.row_type == "Section Group":
				section_totals = self.calculate_section_totals(group_row, child_groups, running_totals)
				data.append({
					"row_type": "Section Group",
					"account_name": group_row.section_name,
					"is_bold": 1,
					**section_totals
				})

				running_totals = {key: 0 for key in running_totals}

		raw_data = copy.deepcopy(data)

		display_keys = [
			'mtd_actual', 'mtd_budget', 'mtd_prev_year',
			'ytd_actual', 'ytd_budget', 'ytd_prev_year']

		for row in data:
			if row.get('row_type') in ['Account Group']:
				row_root_type = row.get('root_type', group.root_type)
				for key in display_keys:
					if key in row and isinstance(row[key], (int, float)):
						row[key] = self.flip_sign_for_display(row[key], row_root_type)

		return data, raw_data

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

	def calculate_group_totals(
		self,
		group,
		company,
		report_date,
		month_start,
		year_start,
		prev_year_date,
		prev_year_month_start,
		prev_year_start
	):
		"""Calculate totals for all accounts in a group, recursively."""
		totals = {key: 0 for key in [
			'mtd_actual', 'mtd_budget', 'mtd_prev_year',
			'ytd_actual', 'ytd_budget', 'ytd_prev_year']}
		
		accounts = frappe.db.sql(
			"""
			WITH RECURSIVE group_tree AS (
				SELECT name FROM `tabAccount Group` WHERE name = %s
				UNION ALL
				SELECT ag.name
				FROM `tabAccount Group` ag
				INNER JOIN `tabAccount Group Row` agr ON agr.account_group = ag.name
				INNER JOIN group_tree gt ON agr.parent = gt.name
				WHERE agr.row_type = 'Account Group'
			)
			SELECT DISTINCT a.name
			FROM `tabAccount` a
			INNER JOIN `tabAccount Group Row` agr ON agr.account = a.name
			WHERE agr.parent IN (SELECT name FROM group_tree) AND agr.row_type = 'Account'
			""",
			(group.name,), as_dict=1
		)
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
		
		account_doc = frappe.get_doc("Account", account)

		balances = {
			"mtd_actual": self.get_balance(account, company, month_start, report_date, account_doc),
			"ytd_actual": self.get_balance(account, company, year_start, report_date, account_doc),
			"mtd_prev_year": self.get_balance(account, company, prev_year_month_start, prev_year_date, account_doc),
			"ytd_prev_year": self.get_balance(account, company, prev_year_start, prev_year_date, account_doc),
			"mtd_budget": self.get_budget_amount(account, company, month_start, report_date, year_start, report_date.year),
			"ytd_budget": self.get_budget_amount(account, company, year_start, report_date, year_start, report_date.year)
		}

		return {
			"row_type": "Account",
			"account_name": f"{account_doc.account_number} - {account_doc.account_name}" if account_doc.account_number else account_doc.account_name,
			"account": account,
			"account_type": account_doc.account_type,
			**balances
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
			SELECT SUM(credit) - SUM(debit)
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

	def flip_sign_for_display(self, value, root_type):
		if root_type == "Income":
			return abs(value)
		elif root_type == "Expense":
			return -abs(value)
		return value