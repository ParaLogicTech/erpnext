import frappe


def execute():
	github_sync_id_cf = frappe.db.get_value("Custom Field", {
		"dt": "Project",
		"fieldname": "github_sync_id",
	})
	hub_sync_id_cf = frappe.db.get_value("Custom Field", {
		"dt": "Item",
		"fieldname": "hub_sync_id",
	})

	if github_sync_id_cf:
		frappe.delete_doc("Custom Field", github_sync_id_cf)
	if hub_sync_id_cf:
		frappe.delete_doc("Custom Field", hub_sync_id_cf)

	if frappe.db.has_column("Project", "github_sync_id"):
		frappe.db.sql_ddl("ALTER TABLE `tabProject` DROP COLUMN `github_sync_id`")

	if frappe.db.has_column("Project", "hub_sync_id"):
		frappe.db.sql_ddl("ALTER TABLE `tabItem` DROP COLUMN `hub_sync_id`")
