import frappe


def execute():
	work_orders = frappe.db.sql_list("""
		select distinct work_order
		from `tabPacking Slip Item`
		where work_order is not null and work_order != '' and rejected_qty != 0 and docstatus = 1
	""")

	for name in work_orders:
		doc = frappe.get_doc("Work Order", name)
		doc.set_packing_status(update=True, update_modified=False)
