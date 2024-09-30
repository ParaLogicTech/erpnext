import frappe

def execute():
	frappe.reload_doc("maintenance", "doctype", "maintenance_schedule_detail")

	frappe.db.sql("""
		UPDATE `tabMaintenance Schedule Detail` AS msd
		INNER JOIN `tabProject Template` AS pt ON pt.name = msd.project_template
		SET msd.project_template_name = pt.project_template_name
	""")
