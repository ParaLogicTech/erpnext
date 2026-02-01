import frappe
from frappe.utils import clean_whitespace


def execute():
	doctypes = [
		"Customer",
		"Employee",
		"Contact",
		"User",
	]

	for dt in doctypes:
		field_prefix = "contact_" if dt == "Customer" else ""

		middle_field = f"{field_prefix}middle_name"
		last_field = f"{field_prefix}last_name"

		data = frappe.get_all(dt, filters={middle_field: ["is", "set"]}, fields=["name", middle_field, last_field])
		for d in data:
			new_last_name = " ".join(filter(None, [d.get(middle_field), d.get(last_field)]))
			new_last_name = clean_whitespace(new_last_name)

			frappe.db.set_value(dt, d.name, {
				middle_field: "",
				last_field: new_last_name,
			}, update_modified=False)
