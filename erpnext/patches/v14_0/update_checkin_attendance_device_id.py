import frappe


def execute():
	frappe.reload_doctype("Employee Checkin")
	frappe.db.sql("""
		update `tabEmployee Checkin` c
		inner join `tabEmployee` e on e.name = c.employee
		set c.attendance_device_id = e.attendance_device_id
	""")
