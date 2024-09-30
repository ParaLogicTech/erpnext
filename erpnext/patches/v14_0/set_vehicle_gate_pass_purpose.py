import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	if 'Vehicles' not in frappe.get_active_domains():
		return

	frappe.reload_doc("vehicles", "doctype", "vehicle_gate_pass")

	frappe.db.sql("update `tabVehicle Gate Pass` set purpose = 'Service - Vehicle Delivery'")

	rename_field("Vehicle Gate Pass", "project_contact_mobile", "contact_mobile")
	rename_field("Vehicle Gate Pass", "project_contact_phone", "contact_phone")
	rename_field("Vehicle Gate Pass", "project_contact_email", "contact_email")
