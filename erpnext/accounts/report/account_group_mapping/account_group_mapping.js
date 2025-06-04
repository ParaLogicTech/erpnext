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
			description: __("Filter by report type for Account Groups and Accounts"),
			reqd: 1
		},
		{
			fieldname: "root_type",
			label: __("Root Type"),
			fieldtype: "Select",
			options: ["", "Income", "Expense", "Asset", "Liability", "Equity"],
			default: "",
			description: __("Filter by root type for Accounts only")
		}
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
	onload: function () {
		const style = document.createElement("style");
		style.innerHTML = `
			.awesomplete {
				z-index: 10010 !important;
			}
	
			.awesomplete > ul {
				z-index: 10010 !important;
				position: absolute !important;
				background: white;
				border: 1px solid #ddd;
				max-height: 200px;
				overflow-y: auto;
			}
	
			.dt-scrollable {
				overflow: visible !important;
			}
	
			.dataTable-cell > .link-field {
				overflow: visible !important;
			}
		`;
		document.head.appendChild(style);
	}
	
};
