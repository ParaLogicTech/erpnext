import frappe


def execute():
	frappe.db.sql("""
		update `tabAppointment` a
		set a.status = 'Converted'
		where a.docstatus = 1 and a.status = 'Closed' and exists(
			select p.name from `tabProject` p where p.appointment = a.name
		)
	""")
