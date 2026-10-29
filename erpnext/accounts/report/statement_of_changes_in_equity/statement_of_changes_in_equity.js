// Copyright (c) 2026, ParaLogic and contributors
// For license information, please see license.txt


frappe.query_reports["Statement of Changes in Equity"] = {
	"filters": [
		{
			"fieldname": "company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1
		},
		{
			"fieldname": "report_date",
			"label": __("Report Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.month_end(),
			"reqd": 1
		}
	],

	onload: function (report) {
		frappe.breadcrumbs.add("Accounts");
	},

	formatter: function (value, row, column, data, default_formatter) {
		return erpnext.financial_statements.summarized_statement_formatter(value, row, column, data, default_formatter);
	}
};
