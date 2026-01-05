import frappe
import click


def execute():
	shift_types = frappe.get_all("Shift Type", pluck="name")
	for name in shift_types:
		doc = frappe.get_doc("Shift Type", name)
		doc.set_working_hours()
		doc.db_set("working_hours", doc.working_hours, update_modified=False)

	attendances = frappe.get_all("Attendance", pluck="name")
	with click.progressbar(attendances, label="Updating Attendance Std Available Hours") as att_names:
		for name in att_names:
			doc = frappe.get_doc("Attendance", name)
			doc.set_standard_hours()
			doc.db_set({
				"standard_working_hours": doc.standard_working_hours,
				"standard_break_hours": doc.standard_break_hours,
				"standard_available_hours": doc.standard_available_hours,
			}, update_modified=False)
			doc.clear_cache()
