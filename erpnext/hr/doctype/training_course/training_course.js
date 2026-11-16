// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Training Course", {
	refresh(frm) {
		if (!frm.doc.__islocal) {
			frm.add_custom_button(__("Training Event"), function () {
				frappe.route_options = {
					course: frm.doc.name
				};
				frappe.set_route("List", "Training Event");
			});
		}
	}
});
