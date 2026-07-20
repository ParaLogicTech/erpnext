import frappe


def execute():
	doctypes = [
		"Quotation",
		"Sales Order",
		"Delivery Note",
		"Proforma Invoice",
		"Sales Invoice",
		"Supplier Quotation",
		"Purchase Order",
		"Purchase Receipt",
		"Purchase Invoice",
	]
	for dt in doctypes:
		if frappe.db.has_column(dt, "other_charges_calculation"):
			frappe.db.sql_ddl(f"ALTER TABLE `tab{dt}` DROP COLUMN `other_charges_calculation`")
