import frappe
from frappe import _
from erpnext.accounts.report.summarized_financial_statements import SummarizedFinancialReport


def execute(filters=None):
	return SummarizedCashFlow(filters).run()


class SummarizedCashFlow(SummarizedFinancialReport):
	gl_fields = [
		'actual', 'prev_closing',
	]

	total_fields = gl_fields
	total_with_display_fields = total_fields + [f"{f}_display" for f in total_fields]

	def run(self):
		self.validate_filters()
		return self.get_columns(), self.get_data()

	def get_account_totals(self, all_accounts):
		template = frappe._dict({f: 0 for f in self.gl_fields})

		current_gl_data = self.get_gl_data(all_accounts, from_date=self.filters.year_start_date, to_date=self.filters.report_date,
			aggregate=True)
		prev_closing_gl_data = self.get_gl_data(all_accounts, from_date=self.filters.prev_year_start, to_date=self.filters.prev_year_end,
			aggregate=True)

		account_totals = {}

		for d in current_gl_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["actual"] += d.credit - d.debit

		for d in prev_closing_gl_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["prev_closing"] += d.credit - d.debit

		return account_totals

	# def get_display_value_multiplier(self, row):
	# 	return -1 if row.get("root_type") in ("Liability", "Equity", "Income") else 1

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
				"fieldname": "actual_display",
				"label": _("As on {0}").format(frappe.format(self.filters.report_date)),
				"fieldtype": "Currency",
				"width": 175,
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
			},
			{
				"fieldname": "prev_closing_display",
				"label": _("As on {0}").format(frappe.format(self.filters.prev_year_end)),
				"fieldtype": "Currency",
				"width": 175,
				"from_date": self.filters.prev_year_start,
				"to_date": self.filters.prev_year_end,
			},
		]

	@staticmethod
	def get_report_type():
		return "Cash Flow"
