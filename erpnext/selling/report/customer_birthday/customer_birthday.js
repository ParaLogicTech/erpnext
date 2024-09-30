// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Customer Birthday"] = {
	"filters": [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1
		},
	],

	formatter: function(value, row, column, data, default_formatter) {
		let style = {};
		let link;

		if (column.fieldname == 'notification') {
			if (data.last_sent_dt) {
				style['color'] = 'green';}
			else if (data.birthday_scheduled_dt) {
				style['color'] = 'blue';
			}
		}
		return default_formatter(value, row, column, data, {css: style, link_href: link, link_target: "_blank"});
	},
};
