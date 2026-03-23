// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

const sales_details_group_by_options = [
	"",
	{label: __("Group by ") + __("Customer"), value: "Group by Customer"},
	{label: __("Group by ") + __("Customer Group"), value: "Group by Customer Group"},
	{label: __("Group by ") + __("Transaction"), value: "Group by Transaction"},
	{label: __("Group by ") + __("Branch"), value: "Group by Branch"},
	{label: __("Group by ") + __("Item"), value: "Group by Item"},
	{label: __("Group by ") + __("Item Group"), value: "Group by Item Group"},
	{label: __("Group by ") + __("Brand"), value: "Group by Brand"},
	{label: __("Group by ") + __("Applies To Item"), value: "Group by Applies To Item"},
	{label: __("Group by ") + __("Applies To Variant Of"), value: "Group by Applies To Variant Of"},
	{label: __("Group by ") + __("Territory"), value: "Group by Territory"},
	{label: __("Group by ") + __("Sales Person"), value: "Group by Sales Person"},
]

frappe.query_reports["Sales Details"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			bold: 1
		},
		{
			fieldname: "doctype",
			label: __("Based On"),
			fieldtype: "Select",
			options: ["Sales Order","Delivery Note","Sales Invoice"],
			default: "Sales Invoice",
			reqd: 1
		},
		{
			fieldname: "qty_field",
			label: __("Quantity Type"),
			fieldtype: "Select",
			options: ["Stock Qty", "Contents Qty", "Transaction Qty"],
			default: "Stock Qty",
			reqd: 1
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1
		},
		{
			fieldname: "transaction_type",
			label: __("Transaction Type"),
			fieldtype: "Link",
			options: "Transaction Type"
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
			get_query: function() {
				return {
					query: "erpnext.controllers.queries.customer_query"
				};
			}
		},
		{
			fieldname: "customer_group",
			label: __("Customer Group"),
			fieldtype: "Link",
			options: "Customer Group"
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
			get_query: function() {
				return {
					query: "erpnext.controllers.queries.item_query",
					filters: {'include_disabled': 1,'include_templates':1}
				}
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
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: function() {
				return {
					filters: {'company': frappe.query_report.get_filter_value("company")}
				}
			},
		},
		{
			fieldname: "applies_to_item",
			label: __("Applies to Item"),
			fieldtype: "Link",
			options: "Item",
			get_query: function() {
				return {
					query: "erpnext.controllers.queries.item_query",
					filters: {'include_disabled': 1, 'include_templates': 1}
				}
			},
		},
		{
			fieldname: "territory",
			label: __("Territory"),
			fieldtype: "Link",
			options: "Territory"
		},
		{
			fieldname: "sales_person",
			label: __("Sales Person"),
			fieldtype: "Link",
			options: "Sales Person"
		},
		{
			fieldname: "account_manager",
			label: __("Account Manager"),
			fieldtype: "Link",
			options: "Sales Person"
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
			fieldname: "group_by_1",
			label: __("Group By Level 1"),
			fieldtype: "Select",
			options: sales_details_group_by_options,
			default: ""
		},
		{
			fieldname: "group_by_2",
			label: __("Group By Level 2"),
			fieldtype: "Select",
			options: sales_details_group_by_options,
			default: ""
		},
		{
			fieldname: "group_by_3",
			label: __("Group By Level 3"),
			fieldtype: "Select",
			options: sales_details_group_by_options,
			default: ""
		},
		{
			fieldname: "totals_only",
			label: __("Group Totals Only"),
			fieldtype: "Check",
		},
		{
			fieldname: "group_same_items",
			label: __("Group Same Items"),
			fieldtype: "Check",
			default: 1
		},
		{
			fieldname: "show_basic_values",
			label: __("Show Basic Values"),
			fieldtype: "Check"
		},
		{
			fieldname: "show_tax_exclusive_values",
			label: __("Show Tax Exclusive Values"),
			fieldtype: "Check"
		},
		{
			fieldname: "show_discount_values",
			label: __("Show Discount Values"),
			fieldtype: "Check"
		},
		{
			fieldname: "include_taxes",
			label: __("Show Detailed Taxes"),
			fieldtype: "Check"
		},
		{
			fieldname: "has_project",
			label: __("Project") + " " + __("Entries Only"),
			fieldtype: "Check",
		},
	],

	formatter: function(value, row, column, data, default_formatter) {
		let style = {};

		if (['qty', 'net_amount', 'base_net_amount', 'grand_total', 'base_grand_total'].includes(column.fieldname)) {
			if (flt(value) < 0) {
				style['color'] = 'var(--red-500)';
			}
		}

		return default_formatter(value, row, column, data, {css: style});
	},

	initial_depth: 1
}


