// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Training Event', {
	onload_post_render: function(frm) {
		frm.get_field("employees").grid.set_multiple_add("employee");
	},
	refresh: function (frm) {
		if (!frm.doc.__islocal && !frm.doc.__unsaved) {
			frm.add_custom_button(__("Training Result"), function () {
				frappe.model.open_mapped_doc({
					method: "erpnext.hr.doctype.training_event.training_event.make_training_result",
					frm: frm
				});
			});
			frm.add_custom_button(__("Training Feedback"), function () {
				frappe.model.open_mapped_doc({
					method: "erpnext.hr.doctype.training_event.training_event.make_training_feedback",
					frm: frm
				});
			});
		}
	},
	start_time: function (frm) {
		set_training_hours(frm);
	},
	end_time: function (frm) {
		set_training_hours(frm);
	}
});

function set_training_hours(frm) {
	if (frm.doc.start_time && frm.doc.end_time) {
		let start = moment(frm.doc.start_time);
		let end = moment(frm.doc.end_time);
		let diff_hours = end.diff(start, "hours", true);

		if (diff_hours > 0) {
			let hours = Math.round(diff_hours);
			if (cint(frm.doc.training_hours) !== hours) {
				frm.set_value("training_hours", hours);
			}
		} else {
			if (frm.doc.training_hours) {
				frm.set_value("training_hours", 0);
			}
		}
	}
}
