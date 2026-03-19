import frappe
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import make_dimension_field_for_doctype


def execute():
	dts = ["Bank Deposit Tool", "Bank Deposit Adjustment"]
	dimensions = frappe.get_all("Accounting Dimension", pluck="name")
	for dimension_name in dimensions:
		dimension_doc = frappe.get_doc("Accounting Dimension", dimension_name)
		for doctype in dts:
			make_dimension_field_for_doctype(doctype, dimension_doc)
