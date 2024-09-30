import frappe


def execute():
	frappe.reload_doc("vehicles", "doctype", "vehicle_booking_order")
	docs = frappe.get_all("Vehicle Booking Order")
	for d in docs:
		doc = frappe.get_doc("Vehicle Booking Order", d.name)
		doc.set_transfer_status(update=True, update_modified=False)
		doc.clear_cache()
