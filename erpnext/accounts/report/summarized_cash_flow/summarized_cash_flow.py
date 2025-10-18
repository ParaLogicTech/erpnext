import frappe
from frappe import _
from erpnext.accounts.report.summarized_financial_statements import SummarizedFinancialReport


def execute(filters=None):
	return SummarizedCashFlow(filters).run()


class SummarizedCashFlow(SummarizedFinancialReport):
	def setup_fields(self):
		self.value_fields = frappe._dict({
			"actual": frappe._dict({
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
				"is_gl_value": 1,
			}),
			"prev_closing": frappe._dict({
				"from_date": self.filters.prev_year_start,
				"to_date": self.filters.prev_year_end,
				"is_gl_value": 1,
			}),
		})

	def run(self):
		self.validate_filters()
		return self.get_columns(), self.get_data()

	def get_account_totals(self, all_accounts):
		return self._get_account_totals(all_accounts, self.value_fields, "credit")

	# def get_display_value_multiplier(self, row):
	# 	return -1 if row.get("root_type") in ("Liability", "Equity", "Income") else 1

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
				"label": _("As on {0}").format(frappe.format(self.value_fields["actual"].to_date)),
				"fieldtype": "Float",
				"width": 175,
				"from_date": self.value_fields["actual"].from_date,
				"to_date": self.value_fields["actual"].to_date,
				"is_value_field": 1,
				"format_link": 1,
			},
			{
				"fieldname": "prev_closing_display",
				"label": _("As on {0}").format(frappe.format(self.value_fields["prev_closing"].to_date)),
				"fieldtype": "Float",
				"width": 175,
				"from_date": self.value_fields["prev_closing"].from_date,
				"to_date": self.value_fields["prev_closing"].to_date,
				"is_value_field": 1,
				"format_link": 1,
			},
		]

	@staticmethod
	def get_report_type():
		return "Cash Flow"
