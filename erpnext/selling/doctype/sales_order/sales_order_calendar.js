// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.views.calendar["Sales Order"] = {
	field_map: {
		"start": "delivery_date",
		"end": "delivery_date",
		"id": "name",
		"title": "customer_name",
		"allDay": "allDay"
	},
	gantt: true,
	filters: [
		{
			"fieldtype": "Link",
			"fieldname": "customer",
			"options": "Customer",
			"label": __("Customer")
		},
		{
			"fieldtype": "Select",
			"fieldname": "delivery_status",
			"options": "\nNot Applicable\To Deliver\nDelivered",
			"label": __("Delivery Status")
		},
		{
			"fieldtype": "Select",
			"fieldname": "billing_status",
			"options": "Not Applicable\nTo Bill\nBilled",
			"label": __("Billing Status")
		},
	],
	get_events_method: "erpnext.selling.doctype.sales_order.sales_order.get_events",
	get_css_class: function(data) {
		if (data.status=="Closed") {
			return "success";
		} else if(data.delivery_status == "To Deliver") {
			if (data.per_delivered) {
				return "warning";
			} else {
				return "danger"
			}
		} else if (data.delivery_status == "Delivered") {
			return "success";
		}
	}
}
