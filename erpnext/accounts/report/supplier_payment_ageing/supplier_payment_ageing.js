// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const spa_group_by_options = [
	"",
	{label: __("Group by ") + __("Supplier"), value: "Group by Supplier"},
	{label: __("Group by ") + __("Supplier Group"), value: "Group by Supplier Group"},
	{label: __("Group by ") + __("Cost Center"), value: "Group by Cost Center"},
	{label: __("Group by ") + __("Branch"), value: "Group by Branch"},
	{label: __("Group by ") + __("Project"), value: "Group by Project"},
]

frappe.query_reports["Supplier Payment Ageing"] = {
	"filters": [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company")
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
			default: frappe.datetime.get_today()
		},
		{
			fieldname: "ageing_based_on",
			label: __("Ageing Based On"),
			fieldtype: "Select",
			options: "Posting Date\nDue Date",
			default: "Posting Date",
		},
		{
			fieldname: "ageing_range",
			label: __("Ageing Range"),
			fieldtype: "Data",
			default: "30, 60, 90, 120",
		},
		{
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
			on_change: () => {
				let supplier = frappe.query_report.get_filter_value('supplier');
				if (supplier) {
					frappe.db.get_value('Supplier', supplier, ["supplier_name", "tax_id"], (value) => {
						frappe.query_report.set_filter_value('supplier_name', value["supplier_name"]);
						frappe.query_report.set_filter_value('tax_id', value["tax_id"]);
					});
				} else {
					frappe.query_report.set_filter_value('supplier_name', "");
					frappe.query_report.set_filter_value('tax_id', "");
				}
			},
			get_query: function() {
				return {
					query: "erpnext.controllers.queries.supplier_query"
				};
			}
		},
		{
			fieldname: "supplier_group",
			label: __("Supplier Group"),
			fieldtype: "Link",
			options: "Supplier Group",
		},
		{
			fieldname: "cost_center",
			label: __("Cost Center"),
			fieldtype: "Link",
			options: "Cost Center",
			get_query: () => {
				return { filters: { company: frappe.query_report.get_filter_value("company") } };
			},
		},
		{
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
		},
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
		},
		{
			fieldname: "group_by",
			label: __("Group By Level 1"),
			fieldtype: "Select",
			options: spa_group_by_options,
			default: ""
		},
		{
			fieldname: "group_by_2",
			label: __("Group By Level 2"),
			fieldtype: "Select",
			options: spa_group_by_options,
			default: ""
		},
		{
			fieldname: "exclude_unallocated",
			label: __("Exclude Unallocated Payment"),
			fieldtype: "Check",
		},
		{
			fieldname: "tax_id",
			label: __("Tax Id"),
			fieldtype: "Data",
			hidden: 1,
		},
		{
			fieldname: "supplier_name",
			label: __("Supplier Name"),
			fieldtype: "Data",
			hidden: 1,
		},
	],

	initial_depth: 1,
};
