import frappe


def execute():
	names = frappe.get_all("Proforma Invoice", {"per_billed": 0, "docstatus": ["<", 2]}, pluck="name")
	for name in names:
		doc = frappe.get_doc("Proforma Invoice", name)
		doc.set_outstanding_amount(update=True, update_modified=False)
		doc.clear_cache()
