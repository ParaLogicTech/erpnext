import frappe


def execute():
	frappe.db.sql("""
		update `tabTask` task
		inner join `tabProject` p on p.name = task.project
		set task.cost_center = p.cost_center
	""")
