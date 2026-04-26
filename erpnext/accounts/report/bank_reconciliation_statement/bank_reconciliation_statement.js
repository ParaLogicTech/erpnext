// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.query_reports["Bank Reconciliation Statement"] = {
	filters: [
		{
			label: __("Bank Account"),
			fieldname: "bank_account",
			fieldtype: "Link",
			options: "Bank Account",
			reqd: 1,
			get_query: () => {
				return {
					filters: {
						is_company_account: 1,
					}
				}
			}
		},
		{
			label: __("From Date"),
			fieldname: "from_date",
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1
		},
		{
			label: __("To Date"),
			fieldname: "to_date",
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 1
		},
	],
	formatter: function(value, row, column, data, default_formatter) {
		let style = {};

		if (column.fieldname == 'credit' && flt(value) > 0) {
			style.color = 'var(--red-700)';
		}
		if (column.fieldname == 'debit' && flt(value) > 0) {
			style.color = 'var(--green-800)';
		}

		return default_formatter(value, row, column, data, {css: style});
	},
	after_datatable_render: function(datatable_obj) {
		var indexes = [];
		for (var i = 0; i < datatable_obj.datamanager.data.length; ++i) {
			if(datatable_obj.datamanager.data[i]._collapsed) {
				indexes.push(i);
			}
		}

		indexes.map(i => datatable_obj.rowmanager.closeSingleNode(i));
	},
	onload: function (query_report) {
		query_report.page.add_inner_button(__("Bank Reconciliation Tool"), () => {
			frappe.route_options = {
				bank_account: query_report.get_filter_value("bank_account"),
				from_date: query_report.get_filter_value("from_date"),
				to_date: query_report.get_filter_value("to_date"),
			}
			frappe.open_in_new_tab = true;
			frappe.set_route("Form", "Bank Reconciliation", "Bank Reconciliation");
		});
	},
	initial_depth: 0
}
