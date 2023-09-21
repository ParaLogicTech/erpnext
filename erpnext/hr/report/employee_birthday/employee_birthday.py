# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _


def execute(filters=None):
	if not filters:
		filters = {}

	columns = get_columns()
	data = get_employees(filters)

	return columns, data


def get_employees(filters):
	conditions = get_conditions(filters)
	return frappe.db.sql("""
		select name, employee_name, date_of_birth,
			branch, department, designation,
			gender, company
		from `tabEmployee`
		where status = 'Active' {0}
	""".format(conditions), as_dict=1)


def get_conditions(filters):
	conditions = ""
	if filters.get("month"):
		month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].index(filters["month"]) + 1
		conditions += " and month(date_of_birth) = {0}".format(frappe.db.escape(month))

	if filters.get("company"):
		conditions += " and company = {0}".format(frappe.db.escape(filters["company"]))

	return conditions


def get_columns():
	show_employee_name = frappe.db.get_single_value("HR Settings", "emp_created_by") != "Full Name"

	columns = [
		{"label": _("Employee"), "fieldname": "name", "fieldtype": "Link", "options": "Employee",
			"width": 80 if show_employee_name else 150, "ignore_user_permissions": 1},
		{"label": _("Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 140},
		{"label": _("Date of Birth"), "fieldname": "date_of_birth", "fieldtype": "Date", "width": 90},
		{"label": _("Designation"), "fieldname": "designation", "fieldtype": "Link", "options": "Designation",
			"width": 150, "ignore_user_permissions": 1},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department", "width": 150},
		{"label": _("Gender"), "fieldname": "gender", "fieldtype": "Data", "width": 100},
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 150},
	]

	if not show_employee_name:
		columns = [c for c in columns if c.get("fieldname") != "employee_name"]

	return columns
