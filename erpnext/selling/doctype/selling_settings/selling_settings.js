// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Selling Settings", {
	setup: function(frm) {
		frm.set_query("selling_price_list", () => frm.events.price_list_filters());
		frm.set_query("retail_price_list", () => frm.events.price_list_filters());
		frm.set_query("default_price_list", "price_lists", () => frm.events.price_list_filters());
	},

	price_list_filters: function() {
		return {
			filters: {
				selling: 1,
			}
		}
	},
});
