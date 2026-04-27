import frappe


def execute():
	frappe.db.sql("""
		update `tabEmployee` emp
		inner join `tabEmployee` ra on ra.name = emp.reports_to
		set emp.reports_to_name = ra.employee_name
	""")
