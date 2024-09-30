import frappe


def execute():
	all_dts = [
		'Quotation', 'Sales Order', 'Delivery Note', 'Sales Invoice',
		'Supplier Quotation', 'Purchase Order', 'Purchase Receipt', 'Purchase Invoice'
	]

	# Sales Orders
	sales_orders = frappe.get_all("Sales Order", pluck="name")
	print(f"Updating {len(sales_orders)} Sales Order statuses")
	for name in sales_orders:
		doc = frappe.get_doc("Sales Order", name)
		doc.set_delivery_status()
		doc.set_production_packing_status()
		doc.set_billing_status()

		doc.db_set({
			"delivery_status": doc.delivery_status,
			"packing_status": doc.packing_status,
			"billing_status": doc.billing_status,
		}, update_modified=False)

		doc.clear_cache()

	# Purchase Orders
	purchase_orders = frappe.get_all("Purchase Order", pluck="name")
	print(f"Updating {len(purchase_orders)} Purchase Order statuses")
	for name in purchase_orders:
		doc = frappe.get_doc("Purchase Order", name)
		doc.set_receipt_status()
		doc.set_billing_status()

		doc.db_set({
			"receipt_status": doc.receipt_status,
			"billing_status": doc.billing_status,
		}, update_modified=False)

		doc.clear_cache()

	# Delivery Notes
	delivery_notes = frappe.get_all("Delivery Note", pluck="name")
	print(f"Updating {len(delivery_notes)} Delivery Note statuses")
	for name in delivery_notes:
		doc = frappe.get_doc("Delivery Note", name)
		doc.set_billing_status()

		doc.db_set({
			"billing_status": doc.billing_status,
		}, update_modified=False)

		doc.clear_cache()

	# Purchase Receipts
	purchase_receipts = frappe.get_all("Purchase Receipt", pluck="name")
	print(f"Updating {len(purchase_receipts)} Purchase Receipt statuses")
	for name in purchase_receipts:
		doc = frappe.get_doc("Purchase Receipt", name)
		doc.set_billing_status()

		doc.db_set({
			"billing_status": doc.billing_status,
		}, update_modified=False)

		doc.clear_cache()

	# Installation Status
	frappe.db.sql("""
		update `tabDelivery Note`
		set installation_status = 'Not Applicable'
	""")

	# Cancelled Status
	for dt in all_dts:
		frappe.db.sql(f"""
			update `tab{dt}`
			set status = 'Cancelled'
			where docstatus = 2
		""")
