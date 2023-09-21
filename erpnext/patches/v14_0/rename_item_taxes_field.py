import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	dts = [
		"Quotation", "Sales Order", "Delivery Note", "Sales Invoice",
		"Supplier Quotation", "Purchase Order", "Purchase Receipt", "Purchase Invoice",
	]

	for dt in dts:
		item_dt = f"{dt} Item"
		frappe.reload_doctype(item_dt)

		if frappe.db.has_column(item_dt, "item_taxes_and_charges"):
			rename_field(item_dt, "item_taxes_and_charges", "item_taxes")
			rename_field(item_dt, "base_item_taxes_and_charges", "base_item_taxes")
