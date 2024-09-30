import frappe
from frappe.utils.fixtures import sync_fixtures


def execute():
	frappe.reload_doctype("Work Order")

	frappe.db.sql("""
		UPDATE `tabWork Order` wo
		INNER JOIN `tabSales Order Item` soi
		ON soi.name = wo.sales_order_item
		SET wo.order_line_no = soi.idx
	""")
