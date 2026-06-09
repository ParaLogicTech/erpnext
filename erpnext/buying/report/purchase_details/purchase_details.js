// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

const purchase_details_group_by_options = [
	"",
	{label: __("Group by ") + __("Supplier"), value: "Group by Supplier"},
	{label: __("Group by ") + __("Supplier Group"), value: "Group by Supplier Group"},
	{label: __("Group by ") + __("Transaction"), value: "Group by Transaction"},
	{label: __("Group by ") + __("Branch"), value: "Group by Branch"},
	{label: __("Group by ") + __("Item"), value: "Group by Item"},
	{label: __("Group by ") + __("Item Group"), value: "Group by Item Group"},
	{label: __("Group by ") + __("Brand"), value: "Group by Brand"},
]

frappe.query_reports["Purchase Details"] = {
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
			options: ["Purchase Order","Purchase Receipt","Purchase Invoice"],
			default: "Purchase Invoice",
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
			fieldname: "name",
			label: __("Document No"),
			fieldtype: "Dynamic Link",
			options: "doctype",
			get_query: () => {
				return {
					filters: {
						docstatus: 1,
					}
				}
			}
		},
		{
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier"
		},
		{
			fieldname: "supplier_group",
			label: __("Supplier Group"),
			fieldtype: "Link",
			options: "Supplier Group"
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
			get_query: function() {
				return {
					query: "erpnext.controllers.queries.item_query",
					filters: {'include_disabled': 1}
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
			fieldname: "transaction_type",
			label: __("Transaction Type"),
			fieldtype: "Link",
			options: "Transaction Type"
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
			options: purchase_details_group_by_options,
			default: ""
		},
		{
			fieldname: "group_by_2",
			label: __("Group By Level 2"),
			fieldtype: "Select",
			options: purchase_details_group_by_options,
			default: ""
		},
		{
			fieldname: "group_by_3",
			label: __("Group By Level 3"),
			fieldtype: "Select",
			options: purchase_details_group_by_options,
			default: ""
		},
		{
			fieldname: "group_same_items",
			label: __("Group Same Items"),
			fieldtype: "Check",
			default: 1
		},
		{
			fieldname: "totals_only",
			label: __("Group Totals Only"),
			fieldtype: "Check",
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
	],

	formatter: function(value, row, column, data, default_formatter) {
		let style = {};

		if (['qty', 'net_amount', 'base_net_amount', 'grand_total', 'base_grand_total'].includes(column.fieldname)) {
			if (flt(value) < 0) {
				style['color'] = 'red';
			}
		}

		return default_formatter(value, row, column, data, {css: style});
	},

	initial_depth: 1
}
