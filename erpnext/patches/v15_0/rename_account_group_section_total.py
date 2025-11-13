import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	frappe.db.sql("""
		update `tabAccount Group Row`
		set row_type = 'Section Total'
		where row_type = 'Section Group'
	""")

	if frappe.db.has_column("Account Group Row", "options"):
		rename_field("Account Group Row", "section_account_groups", "options")
