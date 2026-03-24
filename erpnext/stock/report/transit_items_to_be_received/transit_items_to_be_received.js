// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Transit Items To Be Received"] = {
	"filters": [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			bold: 1
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
			fieldname: "from_warehouse",
			label: __("From Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: function() {
				return {
					filters: {'company': frappe.query_report.get_filter_value("company")}
				}
			},
		},
		{
			fieldname: "to_warehouse",
			label: __("To Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: function() {
				return {
					filters: {'company': frappe.query_report.get_filter_value("company")}
				}
			},
		},
		{
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch"
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
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
		},
	],
	formatter: function(value, row, column, data, default_formatter) {
		let style = {};

		if (column.fieldname == "remaining_qty") {
			style['font-weight'] = 'bold';
		}

		if (column.fieldname == "transferred_qty") {
			if (flt(value)) {
				style['color'] = 'blue';
			}
		}

		if (column.fieldname == "delay_days") {
			if (flt(value) > 0) {
				style['color'] = 'red';
			}
		}

		return default_formatter(value, row, column, data, {css: style});
	},
};
