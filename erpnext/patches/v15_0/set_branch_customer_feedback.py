import frappe
import click

from frappe.utils.fixtures import sync_fixtures


def execute():
    sync_fixtures(app="erpnext")

    frappe.db.sql("""
        update `tabCustomer Feedback` cfb
        inner join `tabProject` p on p.name = cfb.project
        set cfb.branch = p.branch
    """)

    reference_doctypes = frappe.db.sql_list("select distinct reference_doctype from `tabCustomer Feedback`")
    for doctype in reference_doctypes:
        if not doctype or not frappe.get_meta(doctype).has_field("branch"):
            continue

        frappe.db.sql(f"""
            update `tabCustomer Feedback` cfb
            inner join `tab{doctype}` ref on ref.name = cfb.reference_name and cfb.reference_doctype = '{doctype}'
            set cfb.branch = ref.branch
        """)
