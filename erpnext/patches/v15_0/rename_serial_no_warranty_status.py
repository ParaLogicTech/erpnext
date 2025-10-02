import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	frappe.reload_doctype("Serial No")
	frappe.reload_doctype("Vehicle")
	rename_field("Serial No", "maintenance_status", "warranty_status")
	rename_field("Vehicle", "maintenance_status", "warranty_status")
