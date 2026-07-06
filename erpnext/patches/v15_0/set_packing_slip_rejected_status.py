import frappe


def execute():
	frappe.db.sql("""
		update `tabPacking Slip`
		set warehouse = null
		where is_unpack = 1
	""")

	frappe.db.sql("""
		update `tabPacking Slip` ps
		inner join `tabWarehouse` w on w.name = ps.warehouse
		set ps.status = 'Rejected'
		where ps.status = 'In Stock' and ps.docstatus = 1 and w.stock_type = 'Rejected'
	""")
