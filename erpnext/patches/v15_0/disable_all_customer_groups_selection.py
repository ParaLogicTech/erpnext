import frappe
from frappe.utils.nestedset import get_root_of


def execute():
	root_customer_group = get_root_of("Customer Group")
	if not root_customer_group:
		return

	has_root_selected = frappe.db.get_value("Customer", {"customer_group": root_customer_group})
	if has_root_selected:
		return

	frappe.db.set_value("Customer Group", root_customer_group, "disable_selection", 1, update_modified=False)
