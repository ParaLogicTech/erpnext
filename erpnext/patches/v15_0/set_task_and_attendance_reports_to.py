import frappe


def execute():
	frappe.db.sql("""
		update `tabTask` t
		inner join `tabEmployee` emp on emp.name = t.assigned_to
		inner join `tabEmployee` reports_to_emp on reports_to_emp.name = emp.reports_to
		set
			t.reports_to = emp.reports_to,
			t.reports_to_name = reports_to_emp.employee_name
		where reports_to_emp.date_of_joining <= t.exp_start_date or reports_to_emp.date_of_joining is null
	""")

	frappe.db.sql("""
		update `tabAttendance` att
		inner join `tabEmployee` emp on emp.name = att.employee
		inner join `tabEmployee` reports_to_emp on reports_to_emp.name = emp.reports_to
		set
			att.reports_to = emp.reports_to,
			att.reports_to_name = reports_to_emp.employee_name
		where reports_to_emp.date_of_joining <= att.attendance_date or reports_to_emp.date_of_joining is null
	""")
