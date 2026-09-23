import frappe


def execute():
	frappe.db.sql("""
		update `tabSales Order`
		set bill_to = customer, bill_to_name = customer_name
		where bill_to is null or bill_to = ''
	""")
