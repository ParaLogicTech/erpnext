// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Training Feedback', {
	onload: function(frm) {
		frm.add_fetch("training_event", "course", "course");
		frm.add_fetch("training_event", "event_name", "event_name");
		frm.add_fetch("training_event", "trainer_name", "trainer_name");
	},

	refresh: function (frm) {
		if (!frm.doc.__islocal && !frm.doc.__unsaved) {
			if (![1, 2].includes(frm.doc.docstatus)) {
				frm.add_custom_button(__("Resend Link"), function () {
					frappe.call({
						method: "erpnext.hr.doctype.training_feedback.training_feedback.trigger_training_feedback_notification",
						args: {
							training_feedback: frm.doc.name
						},
						freeze: true,
						freeze_message: __("Sending"),
					});
				});
			}
		}
	},
});
