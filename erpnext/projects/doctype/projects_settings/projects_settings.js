// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Projects Settings', {
	setup: function(frm) {
		frm.set_query("default_sales_transaction_type", () => {
			return {
				filters: {
					selling: 1
				}
			}
		})
	}
});
