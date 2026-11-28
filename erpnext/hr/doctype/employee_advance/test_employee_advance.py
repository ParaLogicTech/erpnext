# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import unittest

import frappe
from frappe.utils import nowdate

from erpnext.hr.doctype.employee_advance.employee_advance import make_bank_entry


class TestEmployeeAdvance(unittest.TestCase):
	def test_paid_amount_and_status(self):
		advance = make_employee_advance()

		journal_entry = make_payment_entry(advance)
		journal_entry.submit()

		advance.reload()

		self.assertEqual(advance.paid_amount, 1000)
		# Paid but not claimed yet
		self.assertEqual(advance.status, "Unclaimed")

		# try making over payment: the Journal Entry stops it when it's saved
		self.assertRaises(frappe.ValidationError, make_payment_entry, advance)


def make_payment_entry(advance):
	journal_entry = frappe.get_doc(make_bank_entry("Employee Advance", advance.name))
	journal_entry.cheque_no = "123123"
	journal_entry.cheque_date = nowdate()
	journal_entry.save()

	return journal_entry


def make_employee_advance():
	doc = frappe.new_doc("Employee Advance")
	doc.employee = "_T-Employee-00001"
	doc.company = "_Test company"
	doc.purpose = "For site visit"
	doc.advance_amount = 1000
	doc.posting_date = nowdate()
	doc.advance_account = "_Test Employee Advance - _TC"
	doc.insert()
	doc.submit()

	return doc
