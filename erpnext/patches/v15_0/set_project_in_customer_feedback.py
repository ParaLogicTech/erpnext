import frappe
from frappe.utils.fixtures import sync_fixtures


def execute():
	sync_fixtures(app="erpnext")

	frappe.db.sql("""
		update `tabCustomer Feedback`
		set project = reference_name
		where
			reference_doctype = 'Project'
			and (project = '' or project is null)
	""")
