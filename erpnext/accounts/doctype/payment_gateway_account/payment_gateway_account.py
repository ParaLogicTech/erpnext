# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PaymentGatewayAccount(Document):
	def autoname(self):
		self.name = self.payment_gateway + " - " + self.currency

	def validate(self):
		self.validate_payment_account()
		self.update_default_payment_gateway()
		self.set_as_default_if_not_set()

	def validate_payment_account(self):
		if not self.payment_account:
			return

		company, account_currency, is_group = frappe.db.get_value("Account", self.payment_account,
			["company", "account_currency", "is_group"])

		if company != self.company:
			frappe.throw(_("Payment Account {0} does not belong to Company {1}").format(
				self.payment_account, self.company
			))

		if account_currency != self.currency:
			frappe.throw(_("Payment Account {0} should be of Currency {1}").format(
				self.payment_account, self.currency
			))

		if is_group:
			frappe.throw(_("Payment Account {0} is a group account").format(self.payment_account))

	def update_default_payment_gateway(self):
		if self.is_default:
			frappe.db.sql("""
				update `tabPayment Gateway Account`
				set is_default = 0
				where is_default = 1 and company = %(company)s and currency = %(currency)s
			""", {
				"company": self.company,
				"currency": self.currency,
			})

	def set_as_default_if_not_set(self):
		defualt_gateway_account = frappe.db.get_value("Payment Gateway Account", {
			"is_default": 1,
			"company": self.company,
			"currency": self.currency,
			"name": ("!=", self.name),
		})
		if not defualt_gateway_account:
			self.is_default = 1
