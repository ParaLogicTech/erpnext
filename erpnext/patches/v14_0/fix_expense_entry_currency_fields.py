import frappe


def execute():
	frappe.db.sql("""
		update `tabExpense Entry` set base_total_tax_amount = 0 where base_total_tax_amount is null
	""")
