import frappe


def execute():
	frappe.db.sql("""
		update `tabSales Order`
		set bill_to = customer, bill_to_name = customer_name
	""")

	frappe.db.sql("""
		update `tabSales Order` so
		inner join `tabProject` p on p.name = so.project
		set so.bill_to = p.bill_to, so.bill_to_name = p.bill_to_name
		where p.bill_to is not null and p.bill_to != ''
	""")
