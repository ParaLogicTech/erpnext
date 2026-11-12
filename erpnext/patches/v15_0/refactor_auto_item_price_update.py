import frappe
from frappe.utils import cint


def execute():
	old_buying_settings = frappe.get_single("Buying Settings")

	update_buying_prices_based_on = old_buying_settings.get("update_buying_prices_based_on")
	update_buying_prices_on_submission_of_purchase_order = cint(old_buying_settings.get("update_buying_prices_on_submission_of_purchase_order"))

	frappe.reload_doctype("Stock Settings")
	frappe.reload_doctype("Buying Settings")
	frappe.reload_doctype("Selling Settings")

	frappe.db.set_single_value(
		"Selling Settings",
		"update_prices_based_on",
		"Price List Rate",
		update_modified=False,
	)
	frappe.db.set_single_value(
		"Buying Settings",
		"update_prices_based_on",
		update_buying_prices_based_on or "Price List Rate",
		update_modified=False,
	)

	frappe.db.set_single_value(
		"Buying Settings",
		"update_prices_on_submission_of_purchase_order",
		update_buying_prices_on_submission_of_purchase_order,
		update_modified=False,
	)
