import frappe


def execute():
	# purchase order list
	purchase_order_list = frappe.get_all("Purchase Order", pluck="name")
	for each_po in purchase_order_list:
		po_doc = frappe.get_doc("Purchase Order", each_po)
		for idx, row in enumerate(po_doc.items, start=1):
			row.idx = idx
		po_doc.db_update_all()
	
	# sales order list
	sales_order_list = frappe.get_all("Sales Order", pluck="name")
	for each_so in sales_order_list:
		so_doc = frappe.get_doc("Sales Order", each_so)
		for idx, row in enumerate(so_doc.items, start=1):
			row.idx = idx
		so_doc.db_update_all()