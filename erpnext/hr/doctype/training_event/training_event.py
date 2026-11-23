# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import flt, time_diff_in_hours, time_diff_in_seconds
from erpnext.hr.doctype.employee.employee import get_employee_emails

class TrainingEvent(Document):
	def validate(self):
		self.set_employee_emails()
		self.validate_period()
		self.set_training_hours()

	def set_employee_emails(self):
		self.employee_emails = ', '.join(get_employee_emails([d.employee
			for d in self.employees]))

	def validate_period(self):
		if time_diff_in_seconds(self.end_time, self.start_time) <= 0:
			frappe.throw(_('End time cannot be before start time'))

	def set_training_hours(self):
		if self.start_time and self.end_time:
			self.training_hours = flt(
				time_diff_in_hours(self.end_time, self.start_time),
				self.precision("training_hours"),
			)


@frappe.whitelist()
def make_training_result(source_name, target_doc=None):
	from frappe.model.mapper import get_mapped_doc

	def postprocess(source, target):
		for row in (target.employees or []):
			row.hours = flt(source.training_hours)

	mapping = {
		"Training Event": {
			"doctype": "Training Result",
			"field_map": {
				"name": "training_event",
			},
		},
		"Training Event Employee": {
			"doctype": "Training Result Employee",
		},
	}

	target_doc = get_mapped_doc(
		"Training Event",
		source_name,
		mapping,
		target_doc=target_doc,
		postprocess=postprocess,
	)

	return target_doc


@frappe.whitelist()
def make_training_feedback(source_name, target_doc=None):
	from frappe.model.mapper import get_mapped_doc

	def postprocess(source, target):
		if source.employees and len(source.employees) == 1:
			target.employee = source.employees[0].employee

	mapping = {
		"Training Event": {
			"doctype": "Training Feedback",
			"field_map": {
				"name": "training_event",
				"event_name": "event_name"
			},
		},
	}

	target_doc = get_mapped_doc(
		"Training Event",
		source_name,
		mapping,
		target_doc=target_doc,
		postprocess=postprocess,
	)

	return target_doc
