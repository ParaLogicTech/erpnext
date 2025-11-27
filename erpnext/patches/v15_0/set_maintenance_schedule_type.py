import frappe


def execute():
	frappe.db.sql("""
		update `tabMaintenance Schedule Detail`
		set service_type = 'Maintenance'
	""")
