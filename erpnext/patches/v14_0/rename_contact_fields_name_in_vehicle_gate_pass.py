import frappe
from frappe.model.utils.rename_field import rename_field

def execute():
	frappe.reload_doc("vehicles", "doctype", "vehicle_gate_pass")

	rename_field("Vehicle Gate Pass", "project_contact_mobile", "contact_mobile")
	rename_field("Vehicle Gate Pass", "project_contact_phone", "contact_phone")
	rename_field("Vehicle Gate Pass", "project_contact_email", "contact_email")
