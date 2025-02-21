import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	frappe.reload_doctype("Sales Invoice Payment")
	frappe.reload_doctype("POS Closing Entry Detail")

	if frappe.db.has_column("Sales Invoice Payment", "sending_bank"):
		rename_field("Sales Invoice Payment", "sending_bank", "party_bank")
	if frappe.db.has_column("POS Closing Entry Detail", "sending_bank"):
		rename_field("POS Closing Entry Detail", "sending_bank", "party_bank")
