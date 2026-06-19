import frappe
import click


def execute():
    for cf in frappe.get_all(
        "Customer Feedback",
        fields=["name", "project", "reference_doctype", "reference_name"],
    ):
        branch = None

        if cf.project:
            branch = frappe.get_cached_value("Project", cf.project, "branch")
        elif (
            cf.reference_doctype
            and cf.reference_name
            and frappe.get_meta(cf.reference_doctype).has_field("branch")
        ):
            branch = frappe.get_cached_value(
                cf.reference_doctype,
                cf.reference_name,
                "branch",
            )

        if branch:
            frappe.db.set_value(
                "Customer Feedback",
                cf.name,
                "branch",
                branch,
                update_modified=False,
            )
