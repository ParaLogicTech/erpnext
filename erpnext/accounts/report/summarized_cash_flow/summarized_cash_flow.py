import frappe
from frappe import _
from frappe.utils import add_days
from erpnext.accounts.report.summarized_financial_statements import SummarizedFinancialReport


def execute(filters=None):
	return SummarizedCashFlow(filters).run()


class SummarizedCashFlow(SummarizedFinancialReport):
	def setup_fields(self):
		self.value_fields = frappe._dict({
			"ytd_actual": frappe._dict({
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
				"is_gl_value": 1,
			}),
			"ytd_prev_closing": frappe._dict({
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

	def extend_eval_context(self, context):
		super().extend_eval_context(context)

		def get_opening_balance(account_group):
			return self.get_account_group_balance(account_group, add_days(context.field_info.from_date, -1))

		def get_closing_balance(account_group):
			return self.get_account_group_balance(account_group, context.field_info.to_date)

		def get_fixed_asset_additions(account_group):
			return self.get_asset_additions_and_disposals(
				account_group, context.field_info.from_date, context.field_info.to_date
			)["additions"]

		def get_fixed_asset_disposals(account_group):
			return self.get_asset_additions_and_disposals(
				account_group, context.field_info.from_date, context.field_info.to_date
			)["disposals"]

		context["get_group_opening_balance"] = get_opening_balance
		context["get_group_closing_balance"] = get_closing_balance
		context["get_fixed_asset_additions"] = get_fixed_asset_additions
		context["get_fixed_asset_disposals"] = get_fixed_asset_disposals

	def get_columns(self):
		return [
			{
				"fieldname": "account_display",
				"label": _("Particulars"),
				"fieldtype": "Data",
				"width": 350,
			},
			{
				"fieldname": "ytd_actual_display",
				"label": _("As on {0}").format(frappe.format(self.value_fields["ytd_actual"].to_date)),
				"fieldtype": "Float",
				"width": 175,
				"from_date": self.value_fields["ytd_actual"].from_date,
				"to_date": self.value_fields["ytd_actual"].to_date,
				"is_value_field": 1,
				"format_link": 1,
			},
			{
				"fieldname": "ytd_prev_closing_display",
				"label": _("As on {0}").format(frappe.format(self.value_fields["ytd_prev_closing"].to_date)),
				"fieldtype": "Float",
				"width": 175,
				"from_date": self.value_fields["ytd_prev_closing"].from_date,
				"to_date": self.value_fields["ytd_prev_closing"].to_date,
				"is_value_field": 1,
				"format_link": 1,
			},
		]

	@staticmethod
	def get_report_type():
		return "Cash Flow"
