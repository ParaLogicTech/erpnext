// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Customer Feedback', {
	setup: function(frm) {
		erpnext.setup_applies_to_fields(frm);
	},

	project: function(frm) {
		frm.events.get_project_details(frm);
	},

	get_project_details(frm) {
		if (frm.doc.project) {
			return frappe.call({
				method: 'erpnext.projects.doctype.project.project.get_project_details',
				args: {
					project: frm.doc.project,
					doctype: frm.doc.doctype,
				},
				callback: function(r) {
					if (r.message) {
						frm.set_value(r.message);
					}
				}
			});
		}
	}
});
