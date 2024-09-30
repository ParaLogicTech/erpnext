import frappe


def execute():
	frappe.reload_doctype("Manufacturing Settings")
	doc = frappe.get_single("Manufacturing Settings")
	doc.update_global_defaults()
