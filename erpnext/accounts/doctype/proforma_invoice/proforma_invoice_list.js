// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

// render
frappe.listview_settings['Proforma Invoice'] = {
	add_fields: ["status"],

	get_indicator: function(doc) {
		var status_color = {
			"To Bill": "orange",
			"Billed": "green",
		};
		return [__(doc.status), status_color[doc.status], "status,=,"+doc.status];
	},

	right_column: "grand_total",

	onload: function (listview) {
		erpnext.setup_applies_to_listview_filters(listview);
	},
};
