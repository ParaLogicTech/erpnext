// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Operation', {
	refresh: function(frm) {
		frm.set_query("workstation", () => {
			return erpnext.queries.workstation(frm.doc.name);
		});
	}
});
