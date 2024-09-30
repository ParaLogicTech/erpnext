import frappe
from frappe.utils.fixtures import sync_fixtures


def execute():
	sync_fixtures("erpnext")

	names = frappe.get_all("Sales Person", pluck="name")
	for name in names:
		doc = frappe.get_doc("Sales Person", name)
		doc.set_employee_details(update=True, update_modified=False)
