// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Travel Request', {
	onload: function(frm) {
		erpnext.accounts.dimensions.setup_dimension_filters(frm);
	},
});
