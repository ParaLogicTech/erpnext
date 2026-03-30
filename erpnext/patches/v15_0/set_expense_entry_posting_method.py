import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import cint


def execute():
	use_transaction_date_df = frappe.get_meta("Expense Entry").get_field("use_transaction_date")
	default_use_transaction_date = cint(use_transaction_date_df.default) if use_transaction_date_df else 0

	frappe.reload_doc("accounts", "doctype", "expense_entry")

	frappe.db.sql("""
		update `tabExpense Entry`
		set posting_method = 'Multiple Entries on Bill Date'
	""")

	if frappe.db.has_column("Expense Entry", "use_transaction_date"):
		frappe.db.sql("""
			update `tabExpense Entry`
			set posting_method = 'Multiple Entries on Transaction Date'
			where use_transaction_date = 1
		""")

	if default_use_transaction_date:
		make_property_setter(
			"Expense Entry",
			"posting_method",
			"default",
			"Multiple Entries on Transaction Date",
			"Select",
		)
