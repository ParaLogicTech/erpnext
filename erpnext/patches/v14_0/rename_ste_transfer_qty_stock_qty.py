import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	frappe.reload_doctype("Stock Entry Detail")
	rename_field("Stock Entry Detail", "transfer_qty", "stock_qty")
