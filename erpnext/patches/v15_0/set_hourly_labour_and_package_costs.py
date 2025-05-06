import frappe

def execute():
	projects = frappe.get_all("Project")

	for project in projects:
		project.set_sales_amount(update=True, update_modified=False)