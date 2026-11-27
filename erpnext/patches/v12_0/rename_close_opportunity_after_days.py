import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
    frappe.reload_doc("crm", "doctype", "crm_settings")

    if frappe.db.has_column("CRM Settings", "close_opportunity_after_days"):
        rename_field("CRM Settings", "close_opportunity_after_days", "mark_opportunity_lost_after_days")
