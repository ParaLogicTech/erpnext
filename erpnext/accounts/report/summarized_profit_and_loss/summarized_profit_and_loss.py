# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, add_months, get_last_day, get_first_day, format_date
from erpnext.accounts.report.summarized_financial_statements import SummarizedFinancialReport
from erpnext.accounts.doctype.budget.budget import get_accumulated_monthly_budget
from datetime import timedelta


def execute(filters=None):
	return SummarizedProfitAndLossReport(filters).run()


class SummarizedProfitAndLossReport(SummarizedFinancialReport):
	def setup_fields(self):
		if not self.filters.format:
			self.filters.format = "MTD/YTD"

		if self.filters.format == "Monthly":
			current_start_date = self.filters.year_start_date
			while current_start_date <= self.filters.report_date:
				actual_key = self.get_month_key(current_start_date, "actual")
				budget_key = self.get_month_key(current_start_date, "budget")

				current_end_date = get_last_day(current_start_date)
				if current_end_date > self.filters.report_date:
					current_end_date = self.filters.report_date

				month_label = self.get_month_label(current_start_date, current_end_date)

				self.value_fields[actual_key] = frappe._dict({
					"label": _("{0} Actual").format(month_label),
					"from_date": current_start_date,
					"to_date": current_end_date,
					"is_gl_value": 1,
				})
				self.value_fields[budget_key] = frappe._dict({
					"label": _("{0} Budget").format(month_label),
					"from_date": current_start_date,
					"to_date": current_end_date,
					"is_gl_value": 0,
					"is_budget_value": 1,
				})

				current_start_date = add_months(current_start_date, 1)

			self.value_fields.update({
				"ytd_actual": frappe._dict({
					"label": _("Y.T.D Actual"),
					"from_date": self.filters.year_start_date,
					"to_date": self.filters.report_date,
					"is_gl_value": 1,
				}),
				"ytd_budget": frappe._dict({
					"label": _("Y.T.D Budget"),
					"from_date": self.filters.year_start_date,
					"to_date": self.filters.report_date,
					"is_gl_value": 0,
					"is_budget_value": 1,
				}),
			})
		else:
			self.value_fields = frappe._dict({
				"mtd_actual": frappe._dict({
					"label": _("M.T.D Actual"),
					"from_date": self.filters.month_start_date,
					"to_date": self.filters.report_date,
					"is_gl_value": 1,
				}),
				"mtd_budget": frappe._dict({
					"label": _("M.T.D Budget"),
					"from_date": self.filters.month_start_date,
					"to_date": self.filters.report_date,
					"is_gl_value": 0,
					"is_budget_value": 1,
				}),
				"mtd_prev_year": frappe._dict({
					"label": _("M.T.D Previous Year"),
					"from_date": self.filters.prev_year_month_start,
					"to_date": self.filters.prev_year_date,
					"is_gl_value": 1,
				}),
				"ytd_actual": frappe._dict({
					"label": _("Y.T.D Actual"),
					"from_date": self.filters.year_start_date,
					"to_date": self.filters.report_date,
					"is_gl_value": 1,
				}),
				"ytd_budget": frappe._dict({
					"label": _("Y.T.D Budget"),
					"from_date": self.filters.year_start_date,
					"to_date": self.filters.report_date,
					"is_gl_value": 0,
					"is_budget_value": 1,
				}),
				"ytd_prev_year": frappe._dict({
					"label": _("Y.T.D Previous Year"),
					"from_date": self.filters.prev_year_start,
					"to_date": self.filters.prev_year_date,
					"is_gl_value": 1,
				}),
			})

		if self.filters.hide_budget:
			self.value_fields = frappe._dict({f: field_info for f, field_info in self.value_fields.items() if not field_info.is_budget_value})

		self.gl_fields = frappe._dict({f: field_info for f, field_info in self.value_fields.items() if field_info.is_gl_value})
		self.budget_fields = frappe._dict({f: field_info for f, field_info in self.value_fields.items() if field_info.is_budget_value})

		self.gl_fieldnames = list(self.gl_fields.keys())
		self.budget_fieldnames = list(self.budget_fields.keys())

	def run(self):
		self.validate_filters()
		return self.get_columns(), self.get_data()

	def get_account_totals(self, all_accounts):
		template = frappe._dict({f: 0 for f in self.value_fieldnames})

		aggregate = self.filters.format != "Monthly"
		account_totals = self._get_account_totals(all_accounts, self.gl_fields, "credit", aggregate=aggregate)

		if self.budget_fields:
			budget_data = self.get_budget_data(
				all_accounts,
				self.budget_fields.ytd_budget.from_date,
				self.budget_fields.ytd_budget.to_date,
			)

			budget_totals = self.calculate_budget_totals(budget_data)
			for account, budget in budget_totals.items():
				group = account_totals.setdefault(account, template.copy())
				for fieldname in self.budget_fieldnames:
					group[fieldname] = flt(budget.get(fieldname))

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

		if self.budget_fields:
			budget_data = self.get_budget_data(
				accounts,
				self.budget_fields.ytd_budget.from_date,
				self.budget_fields.ytd_budget.to_date,
			)
			budget_totals = self.calculate_budget_totals(budget_data)
			for fieldname in self.budget_fieldnames:
				result[fieldname] = sum(flt(b.get(fieldname)) for b in budget_totals.values())

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

	def calculate_budget_totals(self, budget_records):
		budget_data = {}
		budget_template = frappe._dict({f: 0 for f in self.budget_fieldnames})

		for row in budget_records:
			total_budget = flt(row.budget_amount) or 0

			fy_start = getdate(row.fy_start)
			fy_end = getdate(row.fy_end)
			fy_days = (fy_end - fy_start).days + 1 if fy_end and fy_start else 365

			entry = budget_data.setdefault(row.account, budget_template.copy())

			for fieldname, field_info in self.budget_fields.items():
				from_date = field_info.from_date
				to_date = field_info.to_date

				overlap_start = max(from_date, fy_start)
				overlap_end = min(to_date, fy_end)

				budget_days = (overlap_end - overlap_start).days + 1 if overlap_end >= overlap_start else 0
				calculated_budget = 0
				if budget_days > 0:
					if row.monthly_distribution:
						calculated_budget = (
							get_accumulated_monthly_budget(row.monthly_distribution, overlap_end, row.fiscal_year, total_budget)
							- get_accumulated_monthly_budget(row.monthly_distribution, overlap_start - timedelta(days=1), row.fiscal_year, total_budget)
						)
					else:
						calculated_budget = (total_budget * budget_days / fy_days)

				entry[fieldname] += -1 * calculated_budget

		return budget_data

	def get_display_value_multiplier(self, row):
		return -1 if row.get("root_type") == "Expense" else 1

	@staticmethod
	def get_month_key(date, suffix):
		date = getdate(date)
		return f"month_{date.month}_{date.year}_{suffix}"

	@staticmethod
	def get_month_label(from_date, to_date):
		first_day = get_first_day(from_date)
		last_date = get_last_day(to_date)

		if from_date == first_day and to_date == last_date:
			return format_date(to_date, "MMM y")
		else:
			return format_date(to_date, "dd MMM y")

	def get_columns(self):
		columns = [
			{
				"fieldname": "account_display",
				"label": _("Particulars"),
				"fieldtype": "Data",
				"width": 350,
			},
		]

		value_width = 120 if self.filters.format == "Monthly" else 140

		for fieldname, field_info in self.value_fields.items():
			columns.append({
				"fieldname": f"{fieldname}_display",
				"label": field_info.label,
				"fieldtype": "Float",
				"width": value_width,
				"from_date": field_info.from_date,
				"to_date": field_info.to_date,
				"is_value_field": 1,
				"format_link": 1 if field_info.is_gl_field else 0,
			})

		return columns

	@staticmethod
	def get_report_type():
		return "Profit and Loss"
