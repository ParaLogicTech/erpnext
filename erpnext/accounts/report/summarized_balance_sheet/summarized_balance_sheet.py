# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erpnext.accounts.report.summarized_financial_statements import SummarizedFinancialReport
from datetime import date, datetime


def execute(filters=None):
	return SummarizedBalanceSheet(filters).run()


class SummarizedBalanceSheet(SummarizedFinancialReport):
	gl_fields = [
		'actual', 'prev_year', 'prev_year_end',
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
		prev_year_end_gl_data = self.get_gl_data(all_accounts, to_date=date(int(str(self.filters.prev_year_date)[:4]), 12, 31), aggregate=True)

		account_totals = {}

		for d in current_gl_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["actual"] += d.debit - d.credit

		for d in prev_year_gl_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["prev_year"] += d.debit - d.credit

		for d in prev_year_end_gl_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["prev_year_end"] += d.debit - d.credit

		return account_totals

	def get_display_value_multiplier(self, row):
		return -1 if row.get("root_type") in ("Liability", "Equity", "Income") else 1

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
				"label": _("Actual ({0})").format(frappe.format(self.filters.report_date)),
				"fieldtype": "Currency",
				"width": 175
			},
			{
				"fieldname": "prev_year_display",
				"label": _("Previous Year ({0})").format(frappe.format(self.filters.prev_year_date)),
				"fieldtype": "Currency",
				"width": 175
			},
			{
				"fieldname": "prev_year_end_display",
				"label": _("Previous Year End ({0})").format(frappe.format(date(int(str(self.filters.prev_year_date)[:4]), 12, 31))),
				"fieldtype": "Currency",
				"width": 300
			}
		]

	def get_previous_year_end_date(self, current_date):
		if isinstance(current_date, str):
			current_date = datetime.strptime(current_date, '%Y-%m-%d')

		return date(current_date.year, 12, 31)

	def get_accounts_in_child_account_group(self, current_group_name, root_group_name, account_map):
		current_group = self.get_account_group_doc(current_group_name)

		for row in current_group.rows:
			if row.row_type == "Account":
				account_map.setdefault(root_group_name, {})[row.account] = {
					"party_type": row.party_type or None,
					"party": row.party or None
				}
			elif row.row_type == "Account Group":
				self.get_accounts_in_child_account_group(row.account_group, root_group_name, account_map)

	@staticmethod
	def get_report_type():
		return "Balance Sheet"
