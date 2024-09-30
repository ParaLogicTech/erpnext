import frappe
from frappe.utils.nestedset import get_root_of


def execute():
	frappe.reload_doctype("Tax Rule")
	rules = frappe.get_all("Tax Rule", pluck="name")
	for name in rules:
		doc = frappe.get_doc("Tax Rule", name)
		doc.set_title()
		if doc.title:
			doc.db_set("title", doc.title, update_modified=False)

	root_customer_group = get_root_of("Customer Group")
	root_supplier_group = get_root_of("Supplier Group")

	frappe.db.sql("""
		update `tabTax Rule`
		set customer_group = ''
		where customer_group = %s
	""", root_customer_group)

	frappe.db.sql("""
		update `tabTax Rule`
		set supplier_group = ''
		where supplier_group = %s
	""", root_supplier_group)
