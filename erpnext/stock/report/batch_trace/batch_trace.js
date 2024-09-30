// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Batch Trace"] = {
	filters: [
		{
			fieldname: "batch_no",
			label: __("Batch"),
			fieldtype: "Link",
			reqd: 1,
			options: "Batch",
		},
	],
	formatter: function(value, row, column, data, default_formatter) {
		var style = {};

		if (['actual_qty'].includes(column.fieldname)) {
			if (flt(value) > 0) {
				style['color'] = 'green';
			} else if (flt(value) < 0) {
				style['color'] = 'red';
			}
		}

		return default_formatter(value, row, column, data, {css: style});
	},
	initial_depth: 0
};
