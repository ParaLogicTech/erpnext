import frappe
from frappe import _
from erpnext.accounts.report.summarized_financial_statements import SummarizedFinancialReport
from frappe.utils import format_date


def execute(filters=None):
	return FinancialRatios(filters).run()


class FinancialRatios(SummarizedFinancialReport):
	date_format = "d MMM y"

	def setup_fields(self):
		self.value_fields = frappe._dict({
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
		})

	def run(self):
		self.validate_filters()
		return self.get_columns(), self.get_data()

	def get_account_totals(self, all_accounts):
		template = frappe._dict({f: 0 for f in self.value_fieldnames})

		account_details = self.get_account_details(all_accounts)
		bs_accounts = []
		pnl_accounts = []

		for account in all_accounts:
			report_type = account_details.get(account, {}).get("report_type")
			if report_type == "Profit and Loss":
				pnl_accounts.append(account)
			else:
				bs_accounts.append(account)

		pnl_mtd_data = self.get_gl_data(
			pnl_accounts,
			from_date=self.value_fields.mtd_actual.from_date,
			to_date=self.value_fields.mtd_actual.to_date,
			aggregate=True,
		)
		pnl_ytd_data = self.get_gl_data(
			pnl_accounts,
			from_date=self.value_fields.ytd_actual.from_date,
			to_date=self.value_fields.ytd_actual.to_date,
			aggregate=True,
		)
		bs_data = self.get_gl_data(
			bs_accounts,
			to_date=self.value_fields.ytd_actual.to_date,
			aggregate=True,
		)

		account_totals = {}
		for d in pnl_mtd_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["mtd_actual"] += d.credit - d.debit
		for d in pnl_ytd_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["ytd_actual"] += d.credit - d.debit
		for d in bs_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["mtd_actual"] += d.debit - d.credit
			group["ytd_actual"] += d.debit - d.credit

		return account_totals

	def get_display_value_multiplier(self, row):
		return -1 if row.get("root_type") in ("Expense", "Equity", "Liability") else 1

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
				"label": _("M.T.D {0}").format(format_date(self.value_fields["mtd_actual"].to_date, self.date_format)),
				"fieldtype": "Float",
				"width": 175,
				"from_date": self.value_fields["mtd_actual"].from_date,
				"to_date": self.value_fields["mtd_actual"].to_date,
				"is_value_field": 1,
				"format_link": 1,
			},
			{
				"fieldname": "ytd_actual_display",
				"label": _("Y.T.D {0}").format(format_date(self.value_fields["ytd_actual"].to_date, self.date_format)),
				"fieldtype": "Float",
				"width": 175,
				"from_date": self.value_fields["ytd_actual"].from_date,
				"to_date": self.value_fields["ytd_actual"].to_date,
				"is_value_field": 1,
				"format_link": 1,
			},
		]

	@staticmethod
	def get_report_type():
		return "Ratios"
