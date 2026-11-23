// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on(cur_frm.doctype, {
	applicant_type: function(frm) {
		frm.set_value("applicant", null);
		frm.set_value("applicant_name", null);
	},
	applicant: function(frm) {
		if (frm.doc.applicant) {
			frappe.model.with_doc(frm.doc.applicant_type, frm.doc.applicant, function() {
				var applicant = frappe.model.get_doc(frm.doc.applicant_type, frm.doc.applicant);
				frm.set_value("applicant_name",
					applicant.employee_name);
			});
		}
		else {
			frm.set_value("applicant_name", null);
		}
	}
});