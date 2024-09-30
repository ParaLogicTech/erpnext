import frappe
from frappe.utils import cint
from frappe.model.utils.rename_field import rename_field


def execute():
	frappe.reload_doc("stock", "doctype", "stock_entry")
	frappe.reload_doc("manufacturing", "doctype", "work_order")

	if frappe.db.has_column("Stock Entry", "scrap_qty"):
		rename_field("Stock Entry", "scrap_qty", "process_loss_qty")

	if frappe.db.has_column("Work Order", "scrap_qty"):
		rename_field("Work Order", "scrap_qty", "process_loss_qty")

	frappe.reload_doc("manufacturing", "doctype", "manufacturing_settings")
	scrap_remaining_by_default = cint(frappe.db.get_value("Manufacturing Settings", None, "scrap_remaining_by_default"))
	frappe.db.set_single_value("Manufacturing Settings", "process_loss_remaining_by_default", scrap_remaining_by_default)
	frappe.db.set_default("process_loss_remaining_by_default", scrap_remaining_by_default)
