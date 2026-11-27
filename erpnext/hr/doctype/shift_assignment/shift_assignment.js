// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Shift Assignment", {
	refresh: function(frm) {
		erpnext.hide_company();
		frm.events.toggle_employee_reqd(frm);
	},

	toggle_employee_reqd: function(frm) {
		frm.set_df_property("employee", "reqd", cint(!frm.doc.global_shift));
	},

	global_shift: function(frm) {
		frm.events.toggle_employee_reqd(frm);
	},
});
