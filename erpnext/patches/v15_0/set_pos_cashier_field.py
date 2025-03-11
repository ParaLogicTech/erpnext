import frappe


def execute():
	frappe.db.sql("""
		update `tabSales Invoice`
		set cashier = owner
		where is_pos = 1
	""")

	frappe.db.sql("""
		update `tabPayment Entry`
		set cashier = owner
		where is_pos = 1
	""")
