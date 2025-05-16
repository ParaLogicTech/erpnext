# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, add_years, get_year_start, flt, cint
from erpnext import get_default_company
from erpnext.accounts.report.financial_statements import get_cost_centers_with_children
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_all_dimension_fields,
	get_accounting_dimensions,
	get_dimension_with_children,
)
from erpnext.accounts.report.summarized_profit_and_loss.summarized_profit_and_loss import BaseSummarizedFinancialReport


def execute(filters=None):
	return SummarizedBalanceReport(filters).run()


class SummarizedBalanceReport(BaseSummarizedFinancialReport):
	gl_fields = [
		'actual', 'prev_year',
	]
	
	total_fields = gl_fields + [f"{f}_display" for f in gl_fields]
	total_with_display_fields = total_fields

	def validate_filters(self):
		super().validate_filters()
		
		self.filters.report_date = getdate(self.filters.report_date)
		self.filters.prev_year_date = add_years(self.filters.report_date, -1)

	def get_report_type(self):
		return "Balance Sheet"


	def get_account_totals(self, current_gl_data, prev_year_gl_data, budget_data=None):
		template = frappe._dict({f: 0 for f in self.gl_fields})
		
		account_totals = {}
		
		for d in current_gl_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["actual"] += d.debit - d.credit
		
		for d in prev_year_gl_data:
			group = account_totals.setdefault(d.account, template.copy())
			group["prev_year"] += d.debit - d.credit
			
		return account_totals

	def get_row(self, row_type, row_value, totals=None, is_bold=False, group_root_type=None):
		row = frappe._dict()

		no_values = True
		if totals is not None:
			no_values = False

		if not no_values:
			for f in self.total_fields:
				row[f] = 0

		if not totals:
			totals = frappe._dict()

		row.update(totals)

		row["row_type"] = row_type
		row["account_name"] = row_value or ""
		row["root_type"] = totals.get("root_type") or group_root_type
		row["is_bold"] = cint(is_bold)
		report_type = frappe.db.get_value("Account Group", row['account_name'], "report_type")


		if not no_values:
			multiplier = -1 if (report_type == "Profit and Loss") or row["root_type"] in ["Liability", "Equity"] else 1
			for f in self.total_fields:
				row[f"{f}_display"] = row[f] * multiplier

		return row

	def get_columns(self):
		return [
			{
				"fieldname": "account_name",
				"label": _( "Account" ),
				"fieldtype": "Data",
				"width": 300
			},
			{
				"fieldname": "actual_display",
				"label": _( "Actual (To Date)" ),
				"fieldtype": "Currency",
				"width": 150
			},
			{
				"fieldname": "prev_year_display",
				"label": _( "Previous Year (To Date)" ),
				"fieldtype": "Currency",
				"width": 150
			}
		]