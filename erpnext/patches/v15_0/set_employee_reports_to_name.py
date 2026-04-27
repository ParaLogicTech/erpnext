import frappe


def execute():
	frappe.db.sql("""
		update `tabEmployee` te
		inner join `tabEmployee` te1 on te.reports_to = te1.name
		set te.reports_to_name = te1.employee_name
		where te.reports_to is not null and te.reports_to != ''
	""")