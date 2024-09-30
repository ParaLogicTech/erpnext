import frappe


def execute():
	frappe.delete_doc_if_exists("DocType", "Shopping Cart Settings")
	frappe.delete_doc_if_exists("Module Def", "Shopping Cart")

	frappe.delete_doc_if_exists("DocType", "Products Settings")
	frappe.delete_doc_if_exists("DocType", "Homepage Section")
	frappe.delete_doc_if_exists("DocType", "Homepage")
	frappe.delete_doc_if_exists("DocType", "Homepage Featured Product")
	frappe.delete_doc_if_exists("DocType", "Homepage Section Card")
	frappe.delete_doc_if_exists("DocType", "Website Attribute")
	frappe.delete_doc_if_exists("DocType", "Website Filter Field")
	frappe.delete_doc_if_exists("Module Def", "Portal")

	frappe.delete_doc_if_exists("DocType", "Project Update")
	frappe.delete_doc_if_exists("DocType", "Project User")
	frappe.delete_doc_if_exists("DocType", "Website Item Group")

	frappe.delete_doc_if_exists("Web Form", "issues")
	frappe.delete_doc_if_exists("Web Form", "tasks")
	frappe.delete_doc_if_exists("Web Form", "student-applicant")
	frappe.delete_doc_if_exists("Web Form", "addresses")
	frappe.delete_doc_if_exists("Web Form", "prescription")
	frappe.delete_doc_if_exists("Web Form", "lab-test")
	frappe.delete_doc_if_exists("Web Form", "lab-test")
	frappe.delete_doc_if_exists("Web Form", "patient-appointments")
	frappe.delete_doc_if_exists("Web Form", "personal-details")
	frappe.delete_doc_if_exists("Web Form", "certification-application-usd")
	frappe.delete_doc_if_exists("Web Form", "certification-application")
	frappe.delete_doc_if_exists("Web Form", "grant-application")
	frappe.delete_doc_if_exists("Web Form", "job-application")

	# Website Settings
	website_settings = frappe.get_single("Website Settings")
	website_settings_changed = False
	if website_settings.home_page == "home":
		website_settings.home_page = "app"
		website_settings_changed = True

	to_remove = []
	for d in website_settings.top_bar_items:
		if d.url == "/all-products":
			to_remove.append(d)

	if to_remove:
		website_settings_changed = True
		for d in to_remove:
			website_settings.remove(d)

	if website_settings_changed:
		website_settings.save()
