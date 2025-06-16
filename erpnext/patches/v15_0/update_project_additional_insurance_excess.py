import frappe


def execute():
	"""Updating Additional Insurance Excess Amount"""
	projects = frappe.get_all("Project", filters={"insurance_excess_percentage": [">", 0]}, pluck="name")

	for i, name in enumerate(projects):
		print(f"{i+1}/{len(projects)}: {name}")
		doc = frappe.get_doc("Project", name)
		doc.set_billing_and_delivery_status(update=True, update_modified=False)
		doc.set_status(update=True)
		doc.clear_cache()
