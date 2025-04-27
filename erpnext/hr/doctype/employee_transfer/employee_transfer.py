# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate
from erpnext.hr.utils import update_employee


class EmployeeTransfer(Document):
	def validate(self):
		self.is_applied = 0
		self.is_reverted = 0
		self.validate_employee_left()
		self.validate_dates()
		self.validate_create_new_employee_id()

	def on_submit(self):
		self.apply_transfer()

	def on_cancel(self):
		self.cancel_transfer()

	def apply_transfer(self):
		# do not apply transfer is future dated
		if getdate(self.transfer_date) > getdate():
			return

		if self.create_new_employee_id:
			self.transfer_to_new_employee()
		else:
			self.update_employee_details()

	def cancel_transfer(self):
		# do not revert if not applied yet or already reverted
		if not self.is_applied or self.is_reverted:
			return

		if self.create_new_employee_id:
			self.revert_transfer_to_new_employee()
		else:
			self.update_employee_details(revert=True)

	def revert_temporary_transfer(self):
		# do not revert if not temporary transfer
		if not self.is_temporary_transfer:
			return

		# do not revert if not applied yet or already reverted
		if not self.is_applied or self.is_reverted:
			return

		self.update_employee_details(revert=True)

	def validate_employee_left(self):
		if frappe.db.get_value("Employee", self.employee, "status") == "Left":
			frappe.throw(_("Cannot transfer Employee with status 'Left'"))

	def validate_dates(self):
		if not self.is_temporary_transfer:
			self.to_date = None

		if self.is_temporary_transfer and not self.to_date:
			frappe.throw(_("To Date is mandatory for temporary transfers"))
		if self.to_date and getdate(self.to_date) < getdate(self.transfer_date):
			frappe.throw(_("To Date cannot be before Transfer Date"))
		if self.to_date and getdate(self.to_date) < getdate():
			frappe.throw(_("To Date cannot be in the past"))

	def validate_create_new_employee_id(self):
		if self.is_temporary_transfer and self.create_new_employee_id:
			frappe.throw(_("Cannot create a new Employee ID for temporary transfers"))

	def update_employee_details(self, revert=False):
		employee = frappe.get_doc("Employee", self.employee)

		employee = update_employee(employee, self.transfer_details, date=self.transfer_date, cancel=revert)
		if self.new_company and self.company != self.new_company:
			employee.company = self.company if revert else self.new_company

		employee.save(ignore_permissions=True)

		if revert:
			self.db_set('is_reverted', 1)
		else:
			self.db_set('is_applied', 1)

	def transfer_to_new_employee(self):
		old_employee = frappe.get_doc("Employee", self.employee)

		new_employee = frappe.copy_doc(old_employee)
		new_employee.name = None
		new_employee.employee_number = None
		new_employee = update_employee(new_employee, self.transfer_details, date=self.transfer_date)

		if self.new_company and self.company != self.new_company:
			new_employee.internal_work_history = []
			new_employee.date_of_joining = self.transfer_date
			new_employee.company = self.new_company

		# move user_id to new employee before insert
		if old_employee.user_id and not self.validate_user_in_details():
			new_employee.user_id = old_employee.user_id
			old_employee.db_set("user_id", "")

		new_employee.insert(ignore_permissions=True)
		self.db_set("new_employee_id", new_employee.name)

		# relieve the old employee
		old_employee.db_set("relieving_date", self.transfer_date)
		old_employee.db_set("status", "Left")

		self.db_set('is_applied', 1)

	def revert_transfer_to_new_employee(self):
		employee = frappe.get_doc("Employee", self.employee)
		if self.new_employee_id:
			frappe.throw(_("Please delete the {0} to cancel this document").format(
				frappe.get_desk_link("Employee", self.new_employee_id)
			))

		employee.status = "Active"
		employee.relieving_date = None

		if self.new_company and self.new_company != self.company:
			employee.company = self.company

		employee.save(ignore_permissions=True)

		self.db_set('is_reverted', 1)

	def validate_user_in_details(self):
		for item in self.transfer_details:
			if item.fieldname == "user_id" and item.new != item.current:
				return True
		return False


def process_future_and_temporary_transfers():
	future_transfers = frappe.get_all("Employee Transfer", filters={
		"docstatus": 1,
		"is_applied": 0,
		"is_reverted": 0,
		"transfer_date": ["=", getdate()],
	}, pluck="name")

	for name in future_transfers:
		doc = frappe.get_doc("Employee Transfer", name)
		try:
			doc.apply_transfer()
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			doc.log_error(
				title="Failed to apply Employee Transfer",
				message=frappe.get_traceback(),
			)
			doc.add_comment("Comment", _("Failed to apply Employee Transfer"))
			frappe.db.commit()

	temporary_transfers = frappe.get_all("Employee Transfer", filters={
		"docstatus": 1,
		"is_temporary_transfer": 1,
		"is_applied": 1,
		"is_reverted": 0,
		"to_date": ["<", getdate()],
	}, pluck="name")

	for name in temporary_transfers:
		doc = frappe.get_doc("Employee Transfer", name)
		try:
			doc.revert_temporary_transfer()
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			doc.log_error(
				title="Failed to revert Temporary Employee Transfer",
				message=frappe.get_traceback(),
			)
			doc.add_comment("Comment", _("Failed to revert Temporary Employee Transfer"))
			frappe.db.commit()


def on_doctype_update():
	frappe.db.add_index("Employee Transfer", ["is_temporary_transfer", "is_reverted"])
