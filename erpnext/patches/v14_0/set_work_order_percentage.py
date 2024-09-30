import frappe


def execute():
	frappe.reload_doctype("Work Order")

	frappe.db.sql("""
		update `tabWork Order`
		set
			per_produced = ROUND(produced_qty / qty * 100, 6),
			per_material_transferred = ROUND(material_transferred_for_manufacturing / qty * 100, 6)
	""")
