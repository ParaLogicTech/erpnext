// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

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
			"fieldname":"range1",
			"label": __("Ageing Range 1"),
			"fieldtype": "Int",
			"default": "30",
			"reqd": 1
		},
		{
			"fieldname":"range2",
			"label": __("Ageing Range 2"),
			"fieldtype": "Int",
			"default": "60",
			"reqd": 1
		},
		{
			"fieldname":"range3",
			"label": __("Ageing Range 3"),
			"fieldtype": "Int",
			"default": "90",
			"reqd": 1
		},
		{
			"fieldname":"range4",
			"label": __("Ageing Range 4"),
			"fieldtype": "Int",
			"default": "120",
			"reqd": 1
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
			"fieldname":"designation",
			"label": __("Designation"),
			"fieldtype": "Link",
			"options": "Designation"
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
			"fieldname":"cost_center",
			"label": __("Cost Center"),
			"fieldtype": "Link",
			"options": "Cost Center"
		},
		{
			"fieldname":"project",
			"label": __("Project"),
			"fieldtype": "Link",
			"options": "Project"
		},
		{
			"fieldname":"finance_book",
			"label": __("Finance Book"),
			"fieldtype": "Link",
			"options": "Finance Book"
		},
		{
			"fieldname":"group_by",
			"label": __("Group By Level 1"),
			"fieldtype": "Select",
			"options": "\nGroup by Employee\nGroup by Department\nGroup by Designation\nGroup by Branch\nGroup by Cost Center\nGroup by Project",
			"default": ""
		},
		{
			"fieldname":"group_by_2",
			"label": __("Group By Level 2"),
			"fieldtype": "Select",
			"options": "\nGroup by Employee\nGroup by Department\nGroup by Designation\nGroup by Branch\nGroup by Cost Center\nGroup by Project",
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
