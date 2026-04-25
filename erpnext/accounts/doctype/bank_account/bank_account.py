# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.contacts.address_and_contact import load_address_and_contact, delete_contact_and_address


class BankAccount(Document):
	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)

	def autoname(self):
		self.name = self.account_name + " - " + self.bank

	def on_trash(self):
		delete_contact_and_address("Bank Account", self.name)

	def validate(self):
		self.validate_company_account()
		self.validate_iban()

	def validate_company_account(self):
		if self.is_company_account:
			if not self.company:
				frappe.throw(_("Company is mandatory for Company Bank Account"))
			if not self.account:
				frappe.throw(_("Bank GL Account is mandatory for Company Bank Account"))
		else:
			self.company = None
			self.account = None
			self.suspense_account = None

		if self.account and frappe.get_cached_value("Account", self.account, "company") != self.company:
			frappe.throw(_("Bank GL Account {0} does not belong to Company {1}").format(
				self.account, self.company
			))
		if self.suspense_account and frappe.get_cached_value("Account", self.suspense_account, "company") != self.company:
			frappe.throw(_("Suspense Account {0} does not belong to Company {1}").format(
				self.suspense_account, self.company
			))

	def validate_iban(self):
		'''
		Algorithm: https://en.wikipedia.org/wiki/International_Bank_Account_Number#Validating_the_IBAN
		'''
		# IBAN field is optional
		if not self.iban:
			return

		def encode_char(c):
			# Position in the alphabet (A=1, B=2, ...) plus nine
			return str(9 + ord(c) - 64)

		# remove whitespaces, upper case to get the right number from ord()
		iban = ''.join(self.iban.split(' ')).upper()

		# Move country code and checksum from the start to the end
		flipped = iban[4:] + iban[:4]

		# Encode characters as numbers
		encoded = [encode_char(c) if ord(c) >= 65 and ord(c) <= 90 else c for c in flipped]

		try:
			to_check = int(''.join(encoded))
		except ValueError:
			frappe.throw(_('IBAN is not valid'))

		if to_check % 97 != 1:
			frappe.throw(_('IBAN is not valid'))


@frappe.whitelist()
def make_bank_account(doctype, docname):
	doc = frappe.new_doc("Bank Account")
	doc.party_type = doctype
	doc.party = docname
	doc.is_default = 1

	return doc


@frappe.whitelist()
def get_party_bank_account(party_type, party):
	return frappe.db.get_value(party_type, party, 'default_bank_account')


@frappe.whitelist()
def get_bank_account_details(bank_account):
	return frappe.db.get_value("Bank Account", bank_account,
		['account', 'suspense_account', 'bank', 'bank_account_no'], as_dict=1)
