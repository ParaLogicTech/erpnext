// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

const er_group_by_options = [
	"",
	{label: __("Group by ") + __("Employee"), value: "Group by Employee"},
	{label: __("Group by ") + __("Department"), value: "Group by Department"},
	{label: __("Group by ") + __("Designation"), value: "Group by Designation"},
	{label: __("Group by ") + __("Branch"), value: "Group by Branch"},
	{label: __("Group by ") + __("Cost Center"), value: "Group by Cost Center"},
	{label: __("Group by ") + __("Project"), value: "Group by Project"},
]

frappe.query_reports["Employees Receivable"] = {
	"filters": [
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company")
		},
		{
			"fieldname":"report_date",
			"label": __("As on Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today()
		},
		{
			"fieldname":"ageing_range",
			"label": __("Ageing Range"),
			"fieldtype": "Data",
			"default": "30, 60, 90, 120",
			"reqd": 0
		},
		{
			"fieldname":"employee",
			"label": __("Employee"),
			"fieldtype": "Link",
			"options": "Employee"
		},
		{
			"fieldname":"department",
			"label": __("Department"),
			"fieldtype": "Link",
			"options": "Department"
		},
		{
			"fieldname":"branch",
			"label": __("Branch"),
			"fieldtype": "Link",
			"options": "Branch"
		},
		{
			"fieldname": "account",
			"label": __("Account"),
			"fieldtype": "Link",
			"options": "Account",
			"get_query": function() {
				var company = frappe.query_report.get_filter_value('company');
				return {
					"doctype": "Account",
					"filters": {
						"company": company,
						"account_type": ["in", ["Payable", "Receivable"]],
						"is_group": 0
					}
				}
			}
		},
		{
			"fieldname": "cost_center",
			"label": __("Cost Center"),
			"fieldtype": "Link",
			"options": "Cost Center",
			get_query: () => {
				return { filters: { company: frappe.query_report.get_filter_value("company") } };
			},
		},
		{
			"fieldname":"project",
			"label": __("Project"),
			"fieldtype": "Link",
			"options": "Project"
		},
		{
			"fieldname":"group_by",
			"label": __("Group By Level 1"),
			"fieldtype": "Select",
			"options": er_group_by_options,
			"default": ""
		},
		{
			"fieldname":"group_by_2",
			"label": __("Group By Level 2"),
			"fieldtype": "Select",
			"options": er_group_by_options,
			"default": ""
		},
	],
	onload: function(report) {
		report.page.add_inner_button(__("Employees Receivable Summary"), function() {
			var filters = report.get_values();
			frappe.set_route('query-report', 'Employees Receivable Summary', {company: filters.company});
		});
		erpnext.utils.add_payment_reconciliation_button("Employee", report.page, () => report.get_values());
	},
	initial_depth: 1
}
