import frappe

def execute():
	frappe.reload_doc("projects", "doctype", "tasks_status")

	projects = frappe.get_all("Project")
	for d in projects:
		doc = frappe.get_doc("Project", d.name)
		doc.set_tasks_status(update=True, update_modified=False)

