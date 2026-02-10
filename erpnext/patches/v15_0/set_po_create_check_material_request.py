import frappe

def execute():
	# Set po_created = 1 where at least one active PO Item exists
	frappe.db.sql("""
		UPDATE `tabMaterial Request` mr
		SET mr.po_created = 1
		WHERE EXISTS (
			SELECT 1
			FROM `tabPurchase Order Item` poi
			WHERE poi.material_request = mr.name
			AND poi.docstatus != 2
		)
	""")