import frappe
from erpnext import get_default_company


def execute():
	company = get_default_company()
	if company:
		frappe.db.set_single_value("Navbar Settings", "app_name", company)
