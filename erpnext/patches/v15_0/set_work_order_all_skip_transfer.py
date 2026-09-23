import frappe


def execute():
	frappe.db.sql("""
		update `tabWork Order` wo
		set wo.skip_transfer = 1
		where wo.docstatus = 1 and wo.skip_transfer = 0 and not exists(
			select i.name from `tabWork Order Item` i where i.parent = wo.name and i.skip_transfer_for_manufacture = 0
		)
	""")
