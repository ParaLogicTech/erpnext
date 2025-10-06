import frappe


def execute():
	varchar_len = frappe.db.VARCHAR_LEN

	if frappe.db.has_column("POS Profile User", "parent"):
		return

	frappe.db.sql(f"""
		ALTER TABLE `tabPOS Profile User`
		ADD COLUMN parent varchar({varchar_len}),
		ADD COLUMN parentfield varchar({varchar_len}),
		ADD COLUMN parenttype varchar({varchar_len}),
		ADD INDEX parent(parent)
	""")
