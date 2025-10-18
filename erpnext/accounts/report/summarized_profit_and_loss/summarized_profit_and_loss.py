# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate
from erpnext.accounts.report.summarized_financial_statements import SummarizedFinancialReport
from erpnext.accounts.doctype.budget.budget import get_accumulated_monthly_budget
from datetime import timedelta


def execute(filters=None):
	return SummarizedProfitAndLossReport(filters).run()


class SummarizedProfitAndLossReport(SummarizedFinancialReport):
	def setup_fields(self):
		self.gl_fields = frappe._dict({
			"mtd_actual": frappe._dict({
				"from_date": self.filters.month_start_date,
				"to_date": self.filters.report_date,
				"is_gl_value": 1,
			}),
			"ytd_actual": frappe._dict({
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
				"is_gl_value": 1,
			}),
			"mtd_prev_year": frappe._dict({
				"from_date": self.filters.prev_year_month_start,
				"to_date": self.filters.prev_year_date,
				"is_gl_value": 1,
			}),
			"ytd_prev_year": frappe._dict({
				"from_date": self.filters.prev_year_start,
				"to_date": self.filters.prev_year_date,
				"is_gl_value": 1,
			}),
		})

		self.budget_fields = frappe._dict({
			"mtd_budget": frappe._dict({
				"from_date": self.filters.month_start_date,
				"to_date": self.filters.report_date,
				"is_gl_value": 0,
				"is_budget_value": 1,
			}),
			"ytd_budget": frappe._dict({
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
				"is_gl_value": 0,
				"is_budget_value": 1,
			}),
		})

		self.value_fields = frappe._dict({**self.gl_fields, **self.budget_fields})
		self.gl_fieldnames = list(self.gl_fields.keys())
		self.budget_fieldnames = list(self.budget_fields.keys())

	def run(self):
		self.validate_filters()
		return self.get_columns(), self.get_data()

	def get_account_totals(self, all_accounts):
		template = frappe._dict({f: 0 for f in self.value_fieldnames})

		account_totals = self._get_account_totals(all_accounts, self.gl_fields, "credit")

		# Fetch budgets for all fiscal years overlapping the calendar YTD
		budget_data = self.get_budget_data(all_accounts, self.filters.year_start_date, self.filters.report_date)
		budget_totals = self.calculate_budget_totals(
			budget_data,
			self.filters.month_start_date, self.filters.report_date,
			self.filters.year_start_date, self.filters.report_date
		)

		for account, budget in budget_totals.items():
			group = account_totals.setdefault(account, template.copy())
			group["mtd_budget"] = flt(budget.get("mtd_budget"))
			group["ytd_budget"] = flt(budget.get("ytd_budget"))

		return account_totals

	def get_net_profit_loss(self):
		result = frappe._dict({f: 0 for f in self.value_fieldnames})

		accounts = frappe.get_all(
			"Account",
			filters={
				"company": self.filters.company,
				"report_type": self.get_report_type(),
				"is_group": 0,
			},
			pluck="name"
		)
		if not accounts:
			return result

		for fieldname, field_info in self.gl_fields.items():
			result[fieldname] = self.get_net_profit_loss_for_period(accounts, field_info.from_date, field_info.to_date)

		# --- Budget Calculation ---
		budget_data = self.get_budget_data(accounts, self.filters.year_start_date, self.filters.report_date)
		budget_totals = self.calculate_budget_totals(
			budget_data,
			self.filters.month_start_date, self.filters.report_date,
			self.filters.year_start_date, self.filters.report_date
		)

		# Sum budget for all accounts
		result["mtd_budget"] = sum(flt(b.get("mtd_budget")) for b in budget_totals.values())
		result["ytd_budget"] = sum(flt(b.get("ytd_budget")) for b in budget_totals.values())

		return result

	def get_net_profit_loss_for_period(self, accounts, from_date, to_date):
		gl_data = self.get_gl_data(accounts, from_date=from_date, to_date=to_date, aggregate=True)

		net = 0
		for row in gl_data:
			net += flt(row.get("credit")) - flt(row.get("debit"))

		return net

	def get_budget_data(self, accounts, from_date, to_date):
		"""Fetch raw budget records for all accounts in bulk for all fiscal years overlapping the date range."""
		if not accounts:
			return []

		accounts = list(accounts)

		fiscal_years = self.get_fiscal_years_for_period(from_date, to_date)
		dimension_conditions, dimension_args = self.get_dimension_conditions()
		
		# Check if any dimension filter is applied
		dimension_filter_applied = bool(dimension_conditions.strip())
		all_budget_records = []
		extra_condition = ""

		for fy in fiscal_years:
			args = {
				"accounts": accounts,
				"fiscal_year": fy['name'],
				**dimension_args,
			}

			if not dimension_filter_applied:
				extra_condition = " AND b.budget_against = 'Cost Center'"

			records = frappe.db.sql(f"""
				SELECT ba.account, ba.budget_amount,b.budget_against, b.monthly_distribution, b.fiscal_year,
					   %(fy_start)s as fy_start, %(fy_end)s as fy_end
				FROM `tabBudget Account` ba
				INNER JOIN `tabBudget` b ON ba.parent = b.name
				WHERE ba.account IN %(accounts)s
					AND b.fiscal_year = %(fiscal_year)s
					AND b.docstatus = 1
					{dimension_conditions}
					{extra_condition}
			""", {**args, "fy_start": fy['year_start_date'], "fy_end": fy['year_end_date']}, as_dict=1)
			all_budget_records.extend(records)

		return all_budget_records

	def get_fiscal_years_for_period(self, start_date, end_date):
		fiscal_years = frappe.db.sql(
			"""
			SELECT name, year_start_date, year_end_date
			FROM `tabFiscal Year`
			WHERE year_end_date >= %(start_date)s
				AND year_start_date <= %(end_date)s
			ORDER BY year_start_date
			""",
			{"start_date": start_date, "end_date": end_date},
			as_dict=True
		)
		return fiscal_years

	def calculate_budget_totals(self, budget_records, mtd_start, mtd_end, ytd_start, ytd_end):
		"""Calculate MTD and YTD budget for each account from raw budget records, supporting multi-fiscal-year."""
		budget_data = {}
		for row in budget_records:
			account = row.account
			budget = row.budget_amount or 0
			monthly_distribution = row.monthly_distribution

			fy_start = getdate(row.fy_start)
			fy_end = getdate(row.fy_end)

			# MTD overlap
			mtd_overlap_start = max(mtd_start, fy_start)
			mtd_overlap_end = min(mtd_end, fy_end)

			mtd_days = (mtd_overlap_end - mtd_overlap_start).days + 1 if mtd_overlap_end >= mtd_overlap_start else 0
			fy_days = (fy_end - fy_start).days + 1 if fy_end and fy_start else 365
			mtd_budget = 0
			if mtd_days > 0:
				if monthly_distribution:
					mtd_budget = (
						get_accumulated_monthly_budget(monthly_distribution, mtd_overlap_end, row.fiscal_year, budget)
						- get_accumulated_monthly_budget(monthly_distribution, mtd_overlap_start - timedelta(days=1), row.fiscal_year, budget)
					)
				else:
					mtd_budget = (budget * mtd_days / fy_days)

			# YTD overlap
			ytd_overlap_start = max(ytd_start, fy_start)
			ytd_overlap_end = min(ytd_end, fy_end)

			ytd_days = (ytd_overlap_end - ytd_overlap_start).days + 1 if ytd_overlap_end >= ytd_overlap_start else 0
			ytd_budget = 0
			if ytd_days > 0:
				if monthly_distribution:
					ytd_budget = (
						get_accumulated_monthly_budget(monthly_distribution, ytd_overlap_end, row.fiscal_year, budget)
						- get_accumulated_monthly_budget(monthly_distribution, ytd_overlap_start - timedelta(days=1), row.fiscal_year, budget)
					)
				else:
					ytd_budget = (budget * ytd_days / fy_days)

			entry = budget_data.setdefault(account, {"mtd_budget": 0, "ytd_budget": 0})
			entry["mtd_budget"] += mtd_budget
			entry["ytd_budget"] += ytd_budget

		return budget_data

	def get_display_value_multiplier(self, row):
		return -1 if row.get("root_type") == "Expense" else 1

	def get_columns(self):
		return [
			{
				"fieldname": "account_display",
				"label": _("Account"),
				"fieldtype": "Data",
				"width": 350,
			},
			{
				"fieldname": "mtd_actual_display",
				"label": _("M.T.D Actual"),
				"fieldtype": "Float",
				"width": 140,
				"from_date": self.value_fields["mtd_actual"].from_date,
				"to_date": self.value_fields["mtd_actual"].to_date,
				"is_value_field": 1,
				"format_link": 1,
			},
			{
				"fieldname": "mtd_budget_display",
				"label": _("M.T.D Budget"),
				"fieldtype": "Float",
				"width": 140,
				"from_date": self.value_fields["mtd_budget"].from_date,
				"to_date": self.value_fields["mtd_budget"].to_date,
				"is_value_field": 1,
			},
			{
				"fieldname": "mtd_prev_year_display",
				"label": _("M.T.D Previous Year"),
				"fieldtype": "Float",
				"width": 140,
				"from_date": self.value_fields["mtd_prev_year"].from_date,
				"to_date": self.value_fields["mtd_prev_year"].to_date,
				"is_value_field": 1,
				"format_link": 1,
			},
			{
				"fieldname": "ytd_actual_display",
				"label": _("Y.T.D Actual"),
				"fieldtype": "Float",
				"width": 140,
				"from_date": self.value_fields["ytd_actual"].from_date,
				"to_date": self.value_fields["ytd_actual"].to_date,
				"is_value_field": 1,
				"format_link": 1,
			},
			{
				"fieldname": "ytd_budget_display",
				"label": _("Y.T.D Budget"),
				"fieldtype": "Float",
				"width": 140,
				"from_date": self.value_fields["ytd_budget"].from_date,
				"to_date": self.value_fields["ytd_budget"].to_date,
				"is_value_field": 1,
			},
			{
				"fieldname": "ytd_prev_year_display",
				"label": _("Y.T.D Previous Year"),
				"fieldtype": "Float",
				"width": 140,
				"from_date": self.value_fields["ytd_prev_year"].from_date,
				"to_date": self.value_fields["ytd_prev_year"].to_date,
				"is_value_field": 1,
				"format_link": 1,
			}
		]

	@staticmethod
	def get_report_type():
		return "Profit and Loss"
