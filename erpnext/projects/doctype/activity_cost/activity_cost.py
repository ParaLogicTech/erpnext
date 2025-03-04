# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class DuplicationError(frappe.ValidationError): pass


class ActivityCost(Document):
	def validate(self):
		self.set_title()
		self.check_unique()

	def set_title(self):
		if self.activity_type and self.employee:
			self.title = _("{0} for {1}").format(self.employee_name or self.employee, self.activity_type)
		elif self.activity_type:
			self.title = self.activity_type
		elif self.employee:
			self.title = self.employee_name or self.employee
		else:
			self.title = _("Default Activity Cost")

	def check_unique(self):
		if self.activity_type and self.employee:
			exists = frappe.db.get_all("Activity Cost", {
				"activity_type": self.activity_type,
				"employee": self.employee,
				"name": ['!=', self.name]
			})
			if exists:
				frappe.throw(_("Activity Cost for Employee {0} against Activity Type {1} already exists").format(
					frappe.bold(self.employee), frappe.bold(self.activity_type)
				), DuplicationError)
		elif self.activity_type:
			exists = frappe.db.get_all("Activity Cost", {
				"activity_type": self.activity_type,
				"employee": ['is', 'not set'],
				"name": ['!=', self.name]
			})
			if exists:
				frappe.throw(_("Activity Cost for Activity Type {0} already exists").format(
					frappe.bold(self.activity_type)
				), DuplicationError)
		elif self.employee:
			exists = frappe.db.get_all("Activity Cost", {
				"employee": self.employee,
				"activity_type": ['is', 'not set'],
				"name": ['!=', self.name]
			})
			if exists:
				frappe.throw(_("Activity Cost for Employee {0} already exists").format(
					frappe.bold(self.employee)
				), DuplicationError)
		else:
			exists = frappe.db.get_all("Activity Cost", {
				"employee": ['is', 'not set'],
				"activity_type": ['is', 'not set'],
				"name": ['!=', self.name]
			})
			if exists:
				frappe.throw(_("Default Activity Cost already exists"), DuplicationError)
