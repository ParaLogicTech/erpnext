// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Vehicle Booking Summary"] = {
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
			fieldname: "from_allocation_period",
			label: __("From Allocation Period"),
			fieldtype: "Link",
			options: "Vehicle Allocation Period",
			on_change: function () {
				var period = frappe.query_report.get_filter_value('from_allocation_period');
				if (period) {
					frappe.query_report.set_filter_value('to_allocation_period', period);
				}
			}
		},
		{
			fieldname: "to_allocation_period",
			label: __("To Allocation Period"),
			fieldtype: "Link",
			options: "Vehicle Allocation Period"
		},
		{
			fieldname: "from_delivery_period",
			label: __("From Delivery Period"),
			fieldtype: "Link",
			options: "Vehicle Allocation Period",
			on_change: function () {
				var period = frappe.query_report.get_filter_value('from_delivery_period');
				if (period) {
					frappe.query_report.set_filter_value('to_delivery_period', period);
				}
			}
		},
		{
			fieldname: "to_delivery_period",
			label: __("To Delivery Period"),
			fieldtype: "Link",
			options: "Vehicle Allocation Period"
		},
		{
			fieldname: "variant_of",
			label: __("Model Item Code"),
			fieldtype: "Link",
			options: "Item",
			get_query: function() {
				return {
					query: "erpnext.controllers.queries.item_query",
					filters: {"is_vehicle": 1, "include_in_vehicle_booking": 1, "include_disabled": 1, "has_variants": 1}
				};
			}
		},
		{
			fieldname: "item_code",
			label: __("Variant Item Code"),
			fieldtype: "Link",
			options: "Item",
			get_query: function() {
				var variant_of = frappe.query_report.get_filter_value('variant_of');
				var filters = {"is_vehicle": 1, "include_in_vehicle_booking": 1, "include_disabled": 1};
				if (variant_of) {
					filters['variant_of'] = variant_of;
				}
				return {
					query: "erpnext.controllers.queries.item_query",
					filters: filters
				};
			}
		},
		{
			fieldname: "vehicle_color",
			label: __("Vehicle Color"),
			fieldtype: "Link",
			options: "Vehicle Color"
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
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier"
		},
		{
			fieldname: "group_by_1",
			label: __("Group By Level 1"),
			fieldtype: "Select",
			options: ["", "Group by Allocation Period", "Group by Delivery Period", "Group by Variant", "Group by Model",
				"Group by Item Group", "Group by Brand"],
			default: "Group by Delivery Period"
		},
		{
			fieldname: "group_by_2",
			label: __("Group By Level 2"),
			fieldtype: "Select",
			options: ["", "Group by Allocation Period", "Group by Delivery Period", "Group by Variant", "Group by Model",
				"Group by Item Group", "Group by Brand"],
			default: "Group by Model"
		},
		{
			fieldname: "group_by_3",
			label: __("Group By Level 3"),
			fieldtype: "Select",
			options: ["", "Group by Allocation Period", "Group by Delivery Period", "Group by Variant", "Group by Model",
				"Group by Item Group", "Group by Brand"],
			default: "Group by Variant"
		}
	],
	// formatter: function(value, row, column, data, default_formatter) {
	// 	var style = {};
	//
	// 	$.each(['customer_outstanding', 'supplier_outstanding', 'undeposited_amount'], function (i, f) {
	// 		if (column.fieldname === f) {
	// 			style['color'] = flt(data[f]) ? 'orange' : 'green';
	// 		}
	// 	});
	// 	if (column.fieldname == 'payment_adjustment' && flt(data.payment_adjustment)) {
	// 		style['color'] = 'red';
	// 	}
	//
	// 	return default_formatter(value, row, column, data, {css: style});
	// },
	"initial_depth": 1
};
