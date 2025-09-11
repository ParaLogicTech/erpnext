import frappe


def execute():
	frappe.db.sql("""
		update `tabSales Invoice` si
		inner join `tabCustomer` c on c.name = si.bill_to
		set si.bill_to_group = c.customer_group
	""")
