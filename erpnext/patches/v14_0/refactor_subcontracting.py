import frappe


def execute():
	doctypes = ["Supplier Quotation", "Purchase Order", "Purchase Receipt", "Purchase Invoice"]

	for dt in doctypes:
		frappe.db.sql(f"""
			update `tab{dt}`
			set is_subcontracted = IF(is_subcontracted = 'Yes', 1, 0)
		""")
		frappe.reload_doctype(dt)
