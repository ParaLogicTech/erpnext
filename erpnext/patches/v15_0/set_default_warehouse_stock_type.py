import frappe


def execute():
	frappe.reload_doc("stock", "doctype", "warehouse")
	frappe.reload_doc("stock", "doctype", "warehouse_type")

	frappe.db.sql("""
		update `tabWarehouse`
		set stock_type = 'Available'
		where stock_type is null or stock_type = ''
	""")
	frappe.db.sql("""
		update `tabWarehouse Type`
		set stock_type = 'Available'
		where stock_type is null or stock_type = ''
	""")
