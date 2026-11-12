// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const group_by_options_production_register = [
	"",
	{label: __("Group by ") + __("Customer"), value: "Group by Customer"},
	{label: __("Group by ") + __("Production Item"), value: "Group by Production Item"},
	{label: __("Group by ") + __("Workstation"), value: "Group by Workstation"},
	{label: __("Group by ") + __("Work Order"), value: "Group by Work Order"},
];

frappe.query_reports["Production Register"] = {
	"filters": [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "based_on",
			label: __("Based On"),
			fieldtype: "Select",
			options: ["Manufacture Entry", "Operation Entry"],
			default: "Manufacture Entry",
			reqd: 1
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 1
		},
		{
			fieldname: "production_item",
			label: __("Production Item"),
			fieldtype: "Link",
			options: "Item",
			get_query: function() {
				return {
					query: "erpnext.controllers.queries.item_query",
					filters: {
						'is_stock_item': 1
					}
				};
			},
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group"
		},
		{
			fieldname: "brand",
			label: __("Brand"),
			fieldtype: "Link",
			options: "Brand"
		},
		{
			fieldname: "customer_provided_items",
			label: __("Customer Provided Items"),
			fieldtype: "Select",
			options: [
				"",
				"Customer Provided Items Only",
				"Exclude Customer Provided Items",
			]
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "operation",
			label: __("Operation"),
			fieldtype: "Link",
			options: "Operation",
		},
		{
			fieldname: "workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
		{
			fieldname: "group_by_1",
			label: __("Group By Level 1"),
			fieldtype: "Select",
			options: group_by_options_production_register,
		},
		{
			fieldname: "group_by_2",
			label: __("Group By Level 2"),
			fieldtype: "Select",
			options: group_by_options_production_register,
		},
		{
			fieldname: "totals_only",
			label: __("Group Totals Only"),
			fieldtype: "Check",
		},
	],
	initial_depth: 1
};
