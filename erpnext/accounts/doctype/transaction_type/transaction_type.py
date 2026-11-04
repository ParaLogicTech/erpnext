# -*- coding: utf-8 -*-
# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint
from frappe.model.document import Document
from erpnext.accounts.party import validate_party_accounts
import json


class TransactionType(Document):
	def validate(self):
		if not self.buying and not self.selling:
			frappe.throw(_("Transaction Type must be at least one of Selling or Buying type"))

		account_type = None
		if self.selling and not self.buying:
			account_type = "Receivable"
		elif self.buying and not self.selling:
			account_type = "Payable"

		allow_multiple = self.selling and self.buying

		validate_party_accounts(self, is_party_doc=False, account_type=account_type, allow_multiple=allow_multiple)


@frappe.whitelist()
def get_transaction_type_details(args, items):
	from erpnext.accounts.party import get_party_account_details
	from erpnext.stock.get_item_details import get_item_defaults_info

	args = json.loads(args) if isinstance(args, str) else args
	args = frappe._dict(args)
	items = json.loads(items) if isinstance(items, str) else items

	party_type = party = account_field = None

	if frappe.get_meta(args.doctype).has_field('debit_to'):
		account_field = 'debit_to'
	elif frappe.get_meta(args.doctype).has_field('credit_to'):
		account_field = 'credit_to'

	if args.letter_of_credit:
		party_type = "Letter of Credit"
		party = args.letter_of_credit
	elif args.supplier:
		party_type = "Supplier"
		party = args.supplier
	elif args.bill_to or args.customer:
		party_type = "Customer"
		party = args.bill_to or args.customer

	out = frappe._dict({
		"items": get_item_defaults_info(args, items),
		"doc": frappe._dict()
	})

	if args.transaction_type_name:
		transaction_type_doc = frappe.get_cached_doc("Transaction Type", args.transaction_type_name)
		if transaction_type_doc.allocate_advances_automatically:
			out.doc.allocate_advances_automatically = cint(transaction_type_doc.allocate_advances_automatically == "Yes")
		if transaction_type_doc.disable_rounded_total:
			out.doc.disable_rounded_total = cint(transaction_type_doc.disable_rounded_total == "Yes")
		if transaction_type_doc.calculate_tax_on_company_currency:
			out.doc.calculate_tax_on_company_currency = cint(transaction_type_doc.calculate_tax_on_company_currency == "Yes")

	if party_type and party:
		party_account_details = get_party_account_details(
			party_type,
			party,
			args.company,
			transaction_type=args.transaction_type_name,
			currency=args.currency,
		)

		out.doc.party_account_currency = party_account_details.party_account_currency

		if account_field:
			out.doc[account_field] = party_account_details.account

		if party_account_details.cost_center:
			out.doc.cost_center = party_account_details.cost_center

	return out
