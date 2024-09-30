import frappe


def execute():
	frappe.reload_doctype("Work Order")
	frappe.db.sql("""
		update `tabWork Order` wo
		inner join `tabSales Order` so on so.name = wo.sales_order
		set wo.customer = so.customer, wo.customer_name = so.customer_name
	""")
