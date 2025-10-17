# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erpnext.accounts.report.summarized_financial_statements import SummarizedFinancialReport


def execute(filters=None):
	return SummarizedBalanceSheet(filters).run()


class SummarizedBalanceSheet(SummarizedFinancialReport):
	gl_fields = [
		'actual', 'prev_year', 'prev_closing',
	]

	total_fields = gl_fields
	total_with_display_fields = total_fields + [f"{f}_display" for f in total_fields]

	def run(self):
		self.validate_filters()
		return self.get_columns(), self.get_data()

	def get_account_totals(self, all_accounts):
		template = frappe._dict({f: 0 for f in self.gl_fields})

		current_gl_data = self.get_gl_data(all_accounts, to_date=self.filters.report_date, aggregate=True)
		prev_year_gl_data = self.get_gl_data(all_accounts, to_date=self.filters.prev_year_date, aggregate=True)
		prev_closing_gl_data = self.get_gl_data(all_accounts, to_date=self.filters.prev_year_end, aggregate=True)

		account_totals = {}

		for d in current_gl_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["actual"] += d.debit - d.credit

		for d in prev_year_gl_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["prev_year"] += d.debit - d.credit

		for d in prev_closing_gl_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["prev_closing"] += d.debit - d.credit

		return account_totals

	def get_display_value_multiplier(self, row):
		return -1 if row.get("root_type") in ("Liability", "Equity", "Income") else 1

	def get_columns(self):
		return [
			{
				"fieldname": "account_display",
				"label": _("Account"),
				"fieldtype": "Data",
				"width": 350,
			},
			{
				"fieldname": "actual_display",
				"label": _("Actual ({0})").format(frappe.format(self.filters.report_date)),
				"fieldtype": "Currency",
				"width": 175,
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
				"is_value_field": 1,
			},
			{
				"fieldname": "prev_year_display",
				"label": _("Previous Year ({0})").format(frappe.format(self.filters.prev_year_date)),
				"fieldtype": "Currency",
				"width": 175,
				"from_date": self.filters.prev_year_start,
				"to_date": self.filters.prev_year_date,
				"is_value_field": 1,
			},
			{
				"fieldname": "prev_closing_display",
				"label": _("Prev. Year Closing ({0})").format(frappe.format(self.filters.prev_year_end)),
				"fieldtype": "Currency",
				"width": 190,
				"from_date": self.filters.prev_year_start,
				"to_date": self.filters.prev_year_end,
				"is_value_field": 1,
			},
		]

	@staticmethod
	def get_report_type():
		return "Balance Sheet"
