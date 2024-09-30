import frappe


def execute():
	wors_orders = frappe.get_all("Work Order", pluck="name")
	for name in wors_orders:
		doc = frappe.get_doc("Work Order", name)
		doc.db_set("transaction_date", frappe.utils.getdate(doc.creation), update_modified=False)
		doc.set_production_status(update=True, update_modified=False)
		doc.set_packing_status(update=True, update_modified=False)
		doc.clear_cache()
