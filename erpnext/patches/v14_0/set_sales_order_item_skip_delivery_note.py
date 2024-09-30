import frappe


def execute():
	frappe.reload_doctype("Sales Order Item")
	frappe.db.sql("""
		update `tabSales Order Item`
		set skip_delivery_note = IF((is_stock_item = 1 or is_fixed_asset = 1) and delivered_by_supplier = 0, 0, 1)
	""")
