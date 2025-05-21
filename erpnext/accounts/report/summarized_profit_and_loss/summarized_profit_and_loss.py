# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from erpnext.accounts.report.summarized_financial_statements import SummarizedFinancialReport
from erpnext.accounts.doctype.budget.budget import get_accumulated_monthly_budget
from datetime import timedelta


def execute(filters=None):
	return SummarizedProfitAndLossReport(filters).run()


class SummarizedProfitAndLossReport(SummarizedFinancialReport):
	gl_fields = [
		'mtd_actual', 'mtd_prev_year',
		'ytd_actual', 'ytd_prev_year',
	]
	budget_fields = [
		'mtd_budget', 'ytd_budget'
	]

	total_fields = gl_fields + budget_fields
	total_with_display_fields = total_fields + [f"{f}_display" for f in total_fields]

	def run(self):
		self.validate_filters()
		return self.get_columns(), self.get_data()

	def get_account_totals(self, all_accounts):
		template = frappe._dict({f: 0 for f in self.gl_fields + self.budget_fields})

		# GL Data
		current_gl_data = self.get_gl_data(all_accounts, from_date=self.filters.year_start_date, to_date=self.filters.report_date)
		prev_year_gl_data = self.get_gl_data(all_accounts, from_date=self.filters.prev_year_start, to_date=self.filters.prev_year_date)

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

		# Budget Data
		budget_data = self.get_budget_data(
			all_accounts,
			self.filters.get('fiscal_year') or self.filters.report_date.year
		)
		budget_totals = self.calculate_budget_totals(budget_data)

		for account, budget in budget_totals.items():
			group = account_totals.setdefault(account, template.copy())
			group["mtd_budget"] = flt(budget.get("mtd_budget"))
			group["ytd_budget"] = flt(budget.get("ytd_budget"))

		return account_totals

	def get_budget_data(self, accounts, fiscal_year):
		"""Fetch raw budget records for all accounts in bulk for the fiscal year"""

		if not accounts:
			return []

		accounts = list(accounts)

		dimension_conditions, dimension_args = self.get_dimension_conditions()

		args = {
			"accounts": accounts,
			"company": self.filters.get('company'),
			"fiscal_year": fiscal_year,
			**dimension_args,
		}
		return frappe.db.sql(f"""
			SELECT ba.account, ba.budget_amount, b.monthly_distribution
			FROM `tabBudget Account` ba
			INNER JOIN `tabBudget` b ON ba.parent = b.name
			WHERE ba.account IN %(accounts)s
				AND b.company = %(company)s
				AND b.fiscal_year = %(fiscal_year)s
				AND b.docstatus = 1
				{dimension_conditions}
		""", args, as_dict=1)

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

			entry = budget_data.setdefault(account, {"mtd_budget": 0, "ytd_budget": 0})
			entry["mtd_budget"] += mtd_budget
			entry["ytd_budget"] += ytd_budget

		return budget_data

	def get_display_value_multiplier(self, row):
		return -1 if row.get("root_type") == "Expense" else 1

	def get_columns(self):
		return [
			{
				"fieldname": "account_name",
				"label": _("Account"),
				"fieldtype": "Dynamic Link",
				"options": "link_type",
				"width": 300
			},
			{
				"fieldname": "mtd_actual_display",
				"label": _("M.T.D Actual"),
				"fieldtype": "Currency",
				"width": 140
			},
			{
				"fieldname": "mtd_budget_display",
				"label": _("M.T.D Budget"),
				"fieldtype": "Currency",
				"width": 140
			},
			{
				"fieldname": "mtd_prev_year_display",
				"label": _("M.T.D Previous Year"),
				"fieldtype": "Currency",
				"width": 140
			},
			{
				"fieldname": "ytd_actual_display",
				"label": _("Y.T.D Actual"),
				"fieldtype": "Currency",
				"width": 140
			},
			{
				"fieldname": "ytd_budget_display",
				"label": _("Y.T.D Budget"),
				"fieldtype": "Currency",
				"width": 140
			},
			{
				"fieldname": "ytd_prev_year_display",
				"label": _("Y.T.D Previous Year"),
				"fieldtype": "Currency",
				"width": 140
			}
		]

	@staticmethod
	def get_report_type():
		return "Profit and Loss"
