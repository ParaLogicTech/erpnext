import frappe
from frappe.installer import install_app
from frappe.core.doctype.installed_applications.installed_applications import get_installed_app_order, update_installed_apps_order


def execute():
	if "crm" in frappe.get_installed_apps():
		return

	install_app("crm", set_as_patched=False, force=True)

	app_order = get_installed_app_order()
	erpnext_index = app_order.index("erpnext")
	app_order.remove("crm")
	app_order.insert(erpnext_index, "crm")
	update_installed_apps_order(app_order)
