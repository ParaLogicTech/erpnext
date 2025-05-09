import frappe

def execute():
    for appt in frappe.get_all("Appointment", fields=["name", "service_template", "service_template_name"]):
        if appt.service_template:
            child = frappe.get_doc({
                "doctype": "Appointment Service Template",
                "service_template": appt.service_template,
                "service_template_name": appt.service_template_name,
                "parent": appt.name,
                "parenttype": "Appointment",
                "parentfield": "appointment_service_templates"
            })
            child.insert(ignore_permissions=True)

            frappe.db.set_value("Appointment", appt.name, {
                "service_template": None,
                "service_template_name": None
            })
