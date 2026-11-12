# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _

class TrainingFeedback(Document):
	def validate(self):
		training_event = frappe.get_doc("Training Event", self.training_event)
		if training_event.docstatus != 1:
			frappe.throw(_('{0} must be submitted').format(_('Training Event')))

	def on_submit(self):
		training_event = frappe.get_doc("Training Event", self.training_event)
		event_status = None
		for e in training_event.employees:
			if e.employee == self.employee:
				event_status = 'Feedback Submitted'
				break

		if event_status:
			frappe.db.set_value("Training Event", self.training_event, "event_status", event_status)

	def after_insert(self):
		if hasattr(super(), "after_insert"):
			super().after_insert()

		self.trigger_training_feedback_notification()

	def trigger_training_feedback_notification(self):
		if getattr(self, "mute_notification", None) or self.flags.mute_notification:
			return

		if self.is_new():
			return

		if self.docstatus in (1, 2):
			return

		self.run_method("notify_training_feedback")

	def set_employee_email(self):
		if not self.employee:
			return

		user_id, company_email, personal_email = frappe.db.get_value(
			"Employee", self.employee, ["user_id", "company_email", "personal_email"]
		)
		self.employee_email = company_email or personal_email or user_id


@frappe.whitelist()
def trigger_training_feedback_notification(training_feedback):
	doc = frappe.get_doc("Training Feedback", training_feedback)
	doc.check_permission("read")
	doc.trigger_training_feedback_notification()

	if doc.flags.notifications_executed:
		frappe.msgprint(_("Training Feedback notification triggered"))
	else:
		frappe.msgprint(_("No notifications configured"))

