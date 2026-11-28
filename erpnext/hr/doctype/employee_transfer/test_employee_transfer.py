# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import unittest

import frappe
from frappe.utils import add_days, getdate

from erpnext.hr.doctype.employee.test_employee import make_employee


class TestEmployeeTransfer(unittest.TestCase):
	def setUp(self):
		make_employee("employee2@transfers.com")
		make_employee("employee3@transfers.com")
		frappe.db.sql("""delete from `tabEmployee Transfer`""")

	def test_submit_before_transfer_date(self):
		transfer_obj = frappe.get_doc({
			"doctype": "Employee Transfer",
			"employee": frappe.get_value("Employee", {"user_id": "employee2@transfers.com"}, "name"),
			"transfer_details": [
				{
				"property": "Designation",
				"current": "Software Developer",
				"new": "Project Manager",
				"fieldname": "designation",
				},
			],
		})
		transfer_obj.transfer_date = add_days(getdate(), 1)
		transfer_obj.save()

		# A transfer dated in the future can be submitted, but is only applied on its date
		designation = frappe.db.get_value("Employee", transfer_obj.employee, "designation")
		transfer_obj.submit()
		self.assertEqual(transfer_obj.docstatus, 1)
		self.assertEqual(frappe.db.get_value("Employee", transfer_obj.employee, "designation"), designation)

	def test_new_employee_creation(self):
		transfer = frappe.get_doc({
			"doctype": "Employee Transfer",
			"employee": frappe.get_value("Employee", {"user_id": "employee3@transfers.com"}, "name"),
			"create_new_employee_id": 1,
			"transfer_date": getdate(),
			"transfer_details": [
				{
				"property": "Designation",
				"current": "Software Developer",
				"new": "Project Manager",
				"fieldname": "designation",
				},
			],
		}).insert()
		transfer.submit()
		self.assertTrue(transfer.new_employee_id)
		self.assertEqual(frappe.get_value("Employee", transfer.new_employee_id, "status"), "Active")
		self.assertEqual(frappe.get_value("Employee", transfer.employee, "status"), "Left")

	def test_user_permissions_move_to_new_employee(self):
		user = "employee4@transfers.com"
		# a previous run moved the user to an employee of the other company
		for name in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
			frappe.db.set_value("Employee", name, "user_id", None)
		frappe.db.delete("User Permission", {"user": user})

		employee = make_employee(user, company="_Test Company")

		transfer = frappe.get_doc({
			"doctype": "Employee Transfer",
			"employee": employee,
			"create_new_employee_id": 1,
			"transfer_date": getdate(),
			"new_company": "_Test Company 1",
			"transfer_details": [
				{
				"property": "Designation",
				"current": "Software Developer",
				"new": "Project Manager",
				"fieldname": "designation",
				},
			],
		}).insert()
		transfer.submit()

		user_permissions = frappe.get_all("User Permission", filters={"user": user}, fields=["allow", "for_value"])
		self.assertEqual(sorted((d.allow, d.for_value) for d in user_permissions), [
			("Company", "_Test Company 1"),
			("Employee", transfer.new_employee_id),
		])
