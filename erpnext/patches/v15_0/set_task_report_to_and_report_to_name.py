import frappe


def execute():
	frappe.db.sql("""
		update `tabTask` t
		inner join `tabEmployee` emp on emp.name = t.assigned_to
		inner join `tabEmployee` reports_to_emp on reports_to_emp.name = emp.reports_to
		set
			t.reports_to = emp.reports_to,
			t.reports_to_name = emp.reports_to_name
		where
			ifnull(t.assigned_to, '') != ''
			and ifnull(emp.reports_to, '') != ''
			and (reports_to_emp.date_of_joining <= t.exp_start_date or reports_to_emp.date_of_joining is null)
	""")
