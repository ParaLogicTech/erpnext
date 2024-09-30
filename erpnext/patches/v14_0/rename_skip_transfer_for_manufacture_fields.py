import frappe


def execute():
	for doctype in ['Item', 'BOM Item', 'Work Order Item', 'BOM Explosion Item']:
		frappe.reload_doctype(doctype)

		frappe.db.sql(f"""
			update `tab{doctype}`
			set skip_transfer_for_manufacture = 1
			where include_item_in_manufacturing = 0
		""")
		frappe.db.sql(f"""
			update `tab{doctype}`
			set skip_transfer_for_manufacture = 0
			where include_item_in_manufacturing = 1
		""")
