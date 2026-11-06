// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Buying Settings', {
	setup: function(frm) {
		frm.set_query("buying_price_list", () => frm.events.price_list_filters());
		frm.set_query("default_price_list", "price_lists", () => frm.events.price_list_filters());
	},

	price_list_filters: function() {
		return {
			filters: {
				buying: 1,
			}
		}
	},
});
