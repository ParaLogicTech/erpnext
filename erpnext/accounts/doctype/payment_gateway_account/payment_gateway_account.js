// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on('Payment Gateway Account', {
	setup(frm) {
		frm.events.setup_queries(frm);
	},

	setup_queries(frm) {
		frm.set_query("payment_account", function() {
			return {
				filters: {
					company: frm.doc.company,
					account_currency: frm.doc.currency,
					is_group: 0,
				}
			};
		});
	}
});
