import frappe

def execute():
    if frappe.db.exists("DocType", "Vehicle Checklist Item"):
        frappe.rename_doc("DocType", "Vehicle Checklist Item", "Checklist Item", force=True)