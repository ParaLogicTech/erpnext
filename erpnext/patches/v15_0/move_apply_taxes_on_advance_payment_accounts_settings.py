import frappe
from frappe.utils import cint


def execute():
	apply_taxes_on_advance_payment = cint(frappe.db.get_single_value("Projects Settings", "apply_taxes_on_advance_payment"))

	frappe.reload_doctype("Accounts Settings")
	frappe.db.set_single_value("Accounts Settings", "apply_taxes_on_advance_payment",
		apply_taxes_on_advance_payment, update_modified=False)
