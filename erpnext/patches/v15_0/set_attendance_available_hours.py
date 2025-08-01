import frappe


def execute():
	frappe.db.sql("""
		update `tabAttendance`
		set available_hours = working_hours - break_hours
	""")
