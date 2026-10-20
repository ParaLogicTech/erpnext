import frappe


def execute():
	frappe.db.sql("""
		update `tabQuotation`
		set submission_date = transaction_date
		where submission_date is null and docstatus != 0
	""")
