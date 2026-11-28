# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe


def create_test_contact_and_address():
	frappe.db.sql("delete from tabContact")
	frappe.db.sql("delete from tabAddress")
	frappe.db.sql("delete from `tabDynamic Link`")
	# Customers keep their primary contact and address in fields of their own, which would now point to deleted records
	frappe.db.sql("update tabCustomer set customer_primary_contact = null, customer_primary_address = null")

	frappe.get_doc({
		"doctype": "Address",
		"address_title": "_Test Address for Customer",
		"address_type": "Office",
		"address_line1": "Station Road",
		"city": "_Test City",
		"state": "Test State",
		"country": "India",
		"links": [
			{
				"link_doctype": "Customer",
				"link_name": "_Test Customer",
			},
		],
	}).insert()

	contact = frappe.get_doc({
		"doctype": "Contact",
		"first_name": "_Test Contact for _Test Customer",
		"links": [
			{
				"link_doctype": "Customer",
				"link_name": "_Test Customer",
			},
		],
	})
	contact.add_email("test_contact_customer@example.com", is_primary=True)
	contact.add_phone("+91 0000000000", is_primary_phone=True)
	contact.insert()


def set_return_against_row_references(doc):
	"""Links each return row to the returned document's first row with the same item, as Make Return does"""
	reference_field = frappe.scrub(doc.doctype) + "_item"
	returned_rows = frappe.get_all(f"{doc.doctype} Item", filters={"parent": doc.return_against},
		fields=["name", "item_code"], order_by="idx")

	for d in doc.items:
		if d.get(reference_field):
			continue

		for returned_row in returned_rows:
			if returned_row.item_code == d.item_code:
				d.set(reference_field, returned_row.name)
				break


def assert_raises_and_rollback(test_case, exception, method, *args, **kwargs):
	"""assertRaises, then undo what the method wrote before raising, e.g. a submit that fails in a Stock Ledger Entry
	after the document and earlier ledger entries were saved"""
	frappe.db.savepoint("assert_raises")
	try:
		test_case.assertRaises(exception, method, *args, **kwargs)
	finally:
		rollback_to_savepoint("assert_raises")


def rollback_to_savepoint(save_point):
	"""Rolls back to a savepoint, and forgets the vouchers reposted since then. The stock ledger keeps them in
	frappe.flags until GL Entries are updated, and would otherwise look for the rolled back vouchers later."""
	frappe.db.rollback(save_point=save_point)
	frappe.flags.stock_ledger_vouchers_reposted = None
	frappe.flags.stock_ledger_vouchers_value_changed = None
