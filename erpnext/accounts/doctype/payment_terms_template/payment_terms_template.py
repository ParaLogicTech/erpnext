# -*- coding: utf-8 -*-
# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document
from frappe.utils import flt, cint, getdate, add_days, get_last_day, add_months
from frappe import _


class PaymentTermsTemplate(Document):
	def validate(self):
		self.validate_invoice_portion()
		self.validate_credit_days()
		self.check_duplicate_terms()

	def validate_invoice_portion(self):
		payment_amount_types = list(set([d.payment_amount_type for d in self.terms]))

		if len(payment_amount_types) == 1 and payment_amount_types[0] == "Percentage":
			total_portion = 0
			for term in self.terms:
				total_portion += flt(term.get('invoice_portion', 0))

			if flt(total_portion, 2) != 100.00:
				frappe.throw(_('Combined invoice portion must equal 100%'))

		if 'Amount' in payment_amount_types:
			if 'Percentage' in payment_amount_types:
				frappe.throw(_("Payment Amount Type 'Percentage' cannot be selected if 'Amount' is selected"))

			for i, term in enumerate(self.terms):
				last_row = i == len(self.terms) - 1
				if term.payment_amount_type == "Remaining Amount" and not last_row:
					frappe.throw(_("Row {0}: Payment Amount Type 'Remaining Amount' can only be set for the last row"))

	def validate_credit_days(self):
		for term in self.terms:
			if cint(term.credit_days) < 0:
				frappe.throw(_('Credit Days cannot be a negative number'))

	def check_duplicate_terms(self):
		terms = []
		for term in self.terms:
			term_info = (term.credit_days, term.credit_months, term.due_date_based_on)
			if term_info in terms:
				frappe.throw(_('The Payment Term at row {0} is possibly a duplicate.').format(term.idx))
			else:
				terms.append(term_info)


@frappe.whitelist()
def get_payment_terms(terms_template, posting_date=None, grand_total=None, bill_date=None, delivery_date=None):
	if not terms_template:
		return

	terms_doc = frappe.get_cached_doc("Payment Terms Template", terms_template)

	schedule = []
	remaining_amount = flt(grand_total)
	for d in terms_doc.get("terms"):
		term_details = get_payment_term_details(d,
			posting_date=posting_date, bill_date=bill_date, delivery_date=delivery_date,
			grand_total=grand_total, remaining_amount=remaining_amount)

		remaining_amount -= term_details.payment_amount
		schedule.append(term_details)

	return schedule


@frappe.whitelist()
def get_payment_term_details(term, posting_date=None, grand_total=None, bill_date=None, delivery_date=None,
		remaining_amount=0.0):
	term_details = frappe._dict()

	if isinstance(term, str):
		# is payment term name
		term = frappe.get_cached_doc("Payment Term", term)
	else:
		# is from child payment terms template table
		term_details.payment_term = term.payment_term

	term_details.description = term.description
	term_details.invoice_portion = term.invoice_portion

	term_details.payment_amount_type = term.payment_amount_type or "Percentage"
	if term_details.payment_amount_type == "Amount":
		term_details.payment_amount = min(term.payment_amount, flt(grand_total))
	elif term_details.payment_amount_type == "Remaining Amount":
		term_details.payment_amount = flt(remaining_amount)
	else:
		term_details.payment_amount = flt(term.invoice_portion) * flt(grand_total) / 100

	if term_details.payment_amount_type in ("Amount", "Remaining Amount"):
		term_details.invoice_portion = flt(term_details.payment_amount / flt(grand_total) * 100) if flt(grand_total) else 0

	term_details.due_date = get_payment_term_due_date(term, posting_date, bill_date, delivery_date=delivery_date)

	if getdate(term_details.due_date) < getdate(posting_date):
		term_details.due_date = posting_date

	term_details.mode_of_payment = term.mode_of_payment

	return term_details


def get_due_date_from_template(terms_template, posting_date=None, bill_date=None, delivery_date=None):
	due_date = None

	template = frappe.get_cached_doc('Payment Terms Template', terms_template)
	for term in template.terms:
		term_due_date = get_payment_term_due_date(term, posting_date=posting_date,
			bill_date=bill_date, delivery_date=delivery_date)

		if term_due_date:
			due_date = max(term_due_date, getdate(due_date or bill_date or posting_date))

	return due_date


def get_payment_term_due_date(term, posting_date=None, bill_date=None, delivery_date=None):
	bill_date = getdate(bill_date or posting_date)
	delivery_date = getdate(delivery_date or bill_date)

	if term.due_date_based_on == "Day(s) after invoice date":
		due_date = add_days(bill_date, term.credit_days)
	elif term.due_date_based_on == "Day(s) after the end of the invoice month":
		due_date = add_days(get_last_day(bill_date), term.credit_days)
	elif term.due_date_based_on == "Month(s) after the end of the invoice month":
		due_date = add_months(get_last_day(bill_date), term.credit_months)
	elif term.due_date_based_on == "Day(s) before delivery date":
		due_date = add_days(delivery_date, term.credit_days * -1)
	else:
		due_date = bill_date

	return due_date
