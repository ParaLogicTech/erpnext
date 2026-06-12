import frappe


def execute():
	frappe.db.sql("""
		update `tabSales Invoice` p
		inner join `tabCustomer` c on c.name = p.bill_to
		set p.customer_group = c.customer_group
	""")

	frappe.db.sql("""
		update `tabSales Order` p
		inner join `tabCustomer` c on c.name = p.bill_to
		set p.customer_group = c.customer_group
	""")

	frappe.db.sql("""
		update `tabQuotation` p
		inner join `tabCustomer` c on c.name = p.bill_to
		set p.customer_group = c.customer_group
	""")
