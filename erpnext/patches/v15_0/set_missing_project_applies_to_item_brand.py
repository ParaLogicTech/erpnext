
import frappe

def execute():
    frappe.db.sql("""
        update `tabProject` p
        inner join `tabItem` i on i.name = p.applies_to_item
        set p.applies_to_item_brand = i.brand
        where ifnull(p.applies_to_item_brand, '') = ''
    """)