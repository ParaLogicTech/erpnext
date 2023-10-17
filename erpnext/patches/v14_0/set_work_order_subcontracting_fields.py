import frappe


def execute():
	frappe.reload_doctype("Work Order")
	frappe.reload_doctype("Work Order Item")

	frappe.db.sql("""
		update `tabWork Order`
		set completed_qty = produced_qty,
			per_completed = per_produced,
			producible_qty = qty,
			subcontracting_status = 'Not Applicable'
	""")

	frappe.db.sql("""
		update `tabWork Order Item`
		set total_qty = required_qty
	""")
