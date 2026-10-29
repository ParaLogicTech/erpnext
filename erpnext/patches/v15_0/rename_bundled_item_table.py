import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	if frappe.db.exists("DocType", "Packed Item"):
		frappe.rename_doc("DocType", "Packed Item", "Bundled Item")

	frappe.reload_doctype("Sales Order")
	frappe.reload_doctype("Delivery Note")
	frappe.reload_doctype("Sales Invoice")

	rename_field("Sales Order", "packed_items", "bundled_items")
	rename_field("Delivery Note", "packed_items", "bundled_items")
	rename_field("Sales Invoice", "packed_items", "bundled_items")
