import frappe


def execute():
	fields = [
		'maintenance_reminder_days_before',
		'maintenance_reminder_time',
		'maintenance_opportunity_reminder_days',
		'default_opportunity_type_for_schedule',
		'auto_create_opportunity_from_schedule',
	]

	frappe.reload_doctype("Projects Settings")
	for fieldname in fields:
		value = frappe.db.get_single_value("CRM Settings", fieldname, cache=False)
		if value:
			frappe.db.set_single_value("Projects Settings", fieldname, value, update_modified=False)
