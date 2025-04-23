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
		if frappe.get_value("Employee", self.employee, "status") == "Left":
			frappe.throw(_("Cannot transfer Employee with status Left"))
		if self.is_temporary_transfer and not self.to_date:
			frappe.throw(_("To Date is required for temporary transfers"))
		if self.to_date and getdate(self.to_date) < getdate(self.transfer_date):
			frappe.throw(_("To Date cannot be before Transfer Date"))
		
		if not self.is_temporary_transfer:
			self.to_date = None

		if self.is_temporary_transfer and self.create_new_employee_id:
			frappe.throw(_("Cannot create a new Employee ID for temporary transfers"))

	def before_submit(self):
		transfer_date = getdate(self.transfer_date)
		
		# Allow future dated transfers but ensure they are properly sequenced
		if self.to_date:
			to_date = getdate(self.to_date)
			if to_date < transfer_date:
				frappe.throw(_("To Date cannot be before Transfer Date"))
		


	def on_submit(self):
		employee = frappe.get_doc("Employee", self.employee)
		if self.create_new_employee_id:
			new_employee = frappe.copy_doc(employee)
			new_employee.name = None
			new_employee.employee_number = None
			new_employee = update_employee(new_employee, self.transfer_details, date=self.transfer_date)
			if self.new_company and self.company != self.new_company:
				new_employee.internal_work_history = []
				new_employee.date_of_joining = self.transfer_date
				new_employee.company = self.new_company
			if employee.user_id and not self.validate_user_in_details():
				new_employee.user_id = employee.user_id
				employee.db_set("user_id", "")
			new_employee.insert()
			self.db_set("new_employee_id", new_employee.name)
			employee.db_set("relieving_date", self.to_date if self.to_date else self.transfer_date)
			employee.db_set("status", "Left")
		else:
			employee = update_employee(employee, self.transfer_details, date=self.transfer_date)
			if self.new_company and self.company != self.new_company:
				employee.company = self.new_company
				employee.date_of_joining = self.transfer_date
			employee.save()



	def on_cancel(self):
		employee = frappe.get_doc("Employee", self.employee)
		if self.create_new_employee_id:
			if self.new_employee_id:
				frappe.throw(_("Please delete the {0} to cancel this document")
					.format(frappe.get_desk_link("Employee", self.new_employee_id)))
			employee.status = "Active"
			employee.relieving_date = ''
		else:
			employee = update_employee(employee, self.transfer_details, cancel=True)
		if self.new_company != self.company:
			employee.company = self.company
		employee.save()



	def validate_user_in_details(self):
		for item in self.transfer_details:
			if item.fieldname == "user_id" and item.new != item.current:
				return True
		return False

	def revert_temporary_transfer(self):
		"""Revert temporary transfer by updating the existing record"""
		if not self.is_temporary_transfer or self.docstatus != 1:
			return

		if self.is_reverted:
			return

		# Get the employee document
		employee = frappe.get_doc("Employee", self.employee)
		
		# Build the reversion details (swapping current/new values)
		for detail in self.transfer_details:
			fieldname = detail.fieldname or detail.property
			
			# Check if field exists in Employee doctype (either standard or custom)
			field_exists = frappe.get_meta("Employee").has_field(fieldname)
			
			if not field_exists:
				continue
			
			# Update the transfer detail (reversing the values) using db_set
			current_value = detail.new
			new_value = detail.current
			detail.db_set('current', current_value)
			detail.db_set('new', new_value)

		# Mark as reverted
		self.db_set('is_reverted', 1)
		
		# Update the employee with the reverted values
		for detail in self.transfer_details:
			if detail.fieldname:
				setattr(employee, detail.fieldname, detail.new)
				
		employee.save()
		
		return {
			"status": "success", 
			"message": "Transfer reverted successfully",
			"reversion": self.name
		}

def check_temporary_transfers():
	"""Check and revert temporary transfers that have reached their end date"""
	transfers = frappe.get_all("Employee Transfer",
		filters={
			"is_temporary_transfer": 1,
			"docstatus": 1,
			"to_date": ["<", frappe.utils.today()],
			"is_reverted": 0
		},
		fields=["name"]
	)
	
	for transfer in transfers:
		try:
			doc = frappe.get_doc("Employee Transfer", transfer.name)
			doc.revert_temporary_transfer()
			frappe.db.commit()
		except Exception as e:
			frappe.log_error(message=f"Failed to revert transfer {transfer.name}: {str(e)}", 
							 reference_doctype="Employee Transfer", 
							 reference_name=transfer.name)
