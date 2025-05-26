import frappe
from frappe.utils.fixtures import sync_fixtures


def execute():
    sync_fixtures(app="erpnext")

    fieldname = "service_template"
    if not frappe.db.has_column("Appointment", "service_template"):
        fieldname = "project_template"

    appointments = frappe.get_all("Appointment", filters={
        fieldname: ['is', 'set']
    }, fields=["name", f"{fieldname} as service_template", f"{fieldname}_name as service_template_name"])

    for appt in appointments:
        if appt.service_template:
            child = frappe.get_doc({
                "doctype": "Appointment Service Template",
                "service_template": appt.service_template,
                "service_template_name": appt.service_template_name,
                "parent": appt.name,
                "parenttype": "Appointment",
                "parentfield": "service_templates"
            })
            child.insert(ignore_permissions=True)

    frappe.delete_doc_if_exists("Custom Field", "Appointment-service_template")
    frappe.delete_doc_if_exists("Custom Field", "Appointment-service_template_name")
    frappe.delete_doc_if_exists("Custom Field", "Appointment-cb1_service_template")
