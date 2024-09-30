import frappe
from erpnext import get_default_company
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils.fixtures import sync_fixtures


def execute():
	sync_fixtures("erpnext")

	company = get_default_company()
	if not company:
		return

	frappe.db.sql("""
		update `tabAppointment Type`
		set company = %s
	""", company)

	if frappe.db.count("Appointment") and frappe.db.get_value("Appointment", filters={"appointment_for": "Customer"}):
		make_property_setter("Appointment", "appointment_for", "default", "Customer", "Select")
