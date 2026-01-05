import frappe
from frappe.model.rename_doc import rename_doc

def execute():
    # List of old_name -> new_name pairs
    doctypes_to_rename = [
        ("Item Group Order", "Item Group Option"),
        ("Brand Order", "Brand Option")
    ]

    for old_name, new_name in doctypes_to_rename:
        if frappe.db.exists("DocType", old_name):
            rename_doc(
                "DocType",
                old_name,
                new_name,
                force=True
            )
