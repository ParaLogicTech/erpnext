// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Account Group Mapping"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1
		},
		{
			fieldname: "report_type",
			label: __("Report Type"),
			fieldtype: "Select",
			options: ["Profit and Loss", "Balance Sheet"],
			default: "Profit and Loss",
			description: __("Filter by Report Type for Account Groups and Accounts"),
			reqd: 1
		},
		{
			fieldname: "root_type",
			label: __("Root Type"),
			fieldtype: "Select",
			options: ["", "Income", "Expense", "Asset", "Liability", "Equity"],
			description: __("Filter by Root Type for Accounts only")
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.defaults.get_user_default("year_start_date"),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
		},
		{
			fieldname: "filter_without_entries",
			label: __("Filter Accounts Without Entries"),
			fieldtype: "Check",
		},
	],

	onChange: function (new_value, column, data) {
		const old_value = data[column.fieldname];

		frappe.call({
			method: "erpnext.accounts.report.account_group_mapping.account_group_mapping.update_account_group_mapping",
			args: {
				account: data.account,
				old_group: old_value,
				new_group: new_value
			},
			callback: function () {
				frappe.query_report.refresh();
			}
		});
	},
};
