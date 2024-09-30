import frappe
from frappe.utils.fixtures import sync_fixtures


def execute():
	frappe.reload_doctype("Task")

	frappe.db.sql("UPDATE `tabTask` SET is_overdue = 1, status = 'Working' WHERE status = 'Overdue'")
