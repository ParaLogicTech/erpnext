import frappe
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_doctypes_with_dimensions, get_accounting_dimensions


def execute():
	dimensions = get_accounting_dimensions(cache=False)
	doctypes = get_doctypes_with_dimensions()

	for dt in doctypes:
		for field in dimensions:
			frappe.db.sql("""
				update `tabCustom Field`
				set is_system_generated = 0
				where fieldname = %s and dt = %s
			""", (field, dt))
