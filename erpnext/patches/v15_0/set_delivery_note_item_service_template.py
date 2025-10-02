import frappe


def execute():
	frappe.db.sql("""
		update `tabDelivery Note Item` dni
		inner join `tabSales Order Item` soi on soi.name = dni.sales_order_item
		set dni.service_template = soi.service_template, dni.service_template_detail = soi.service_template_detail
	""")
