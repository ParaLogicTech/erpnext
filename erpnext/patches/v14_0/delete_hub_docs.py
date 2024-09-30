import frappe


def execute():
	frappe.delete_doc_if_exists("DocType", "Marketplace Settings")
	frappe.delete_doc_if_exists("DocType", "Hub Tracked Item")
	frappe.delete_doc_if_exists("DocType", "Hub User")
	frappe.delete_doc_if_exists("DocType", "Hub Users")

	frappe.delete_doc_if_exists("Page", "Hub")

	frappe.delete_doc_if_exists("Module Def", "Hub Node")
