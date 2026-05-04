# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate
from frappe.model.document import Document


class OverlapError(frappe.ValidationError):
	pass


class AccountingPeriod(Document):
	def validate(self):
		self.validate_dates()
		self.validate_overlap()

	def before_insert(self):
		self.bootstrap_doctypes_for_closing()

	def autoname(self):
		company_abbr = frappe.get_cached_value('Company',  self.company,  "abbr")
		self.name = " - ".join([self.period_name, company_abbr])

	def validate_dates(self):
		if getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End Date must be after Start Date"))

	def validate_overlap(self):
		existing_accounting_period = frappe.db.sql("""
			select name
			from `tabAccounting Period`
			where start_date <= %(end_date)s
				and end_date >= %(start_date)s
				and name != %(name)s
				and company = %(company)s
		""", {
			"start_date": self.start_date,
			"end_date": self.end_date,
			"name": self.name,
			"company": self.company
		}, as_dict=True)

		if existing_accounting_period:
			frappe.throw(_("Accounting Period overlaps with {0}").format(
				existing_accounting_period[0].get("name")
			), OverlapError)

	@frappe.whitelist()
	def get_doctypes_for_closing(self):
		doctypes = [
			"Sales Invoice",
			"Purchase Invoice",
			"Journal Entry",
			"Payroll Entry",
			"Bank Reconciliation",
			"Asset",
			"Stock Entry",
			"Stock Reconciliation",
			"Delivery Note",
			"Payment Entry",
			"Purchase Receipt",
			"Period Closing Voucher",
			"Service Maintenance Contract",
			"Service Warranty"
		]

		docs_for_closing = []
		closed_doctypes = [{"document_type": doctype, "closed": 1} for doctype in doctypes]
		for closed_doctype in closed_doctypes:
			docs_for_closing.append(closed_doctype)

		return docs_for_closing

	def bootstrap_doctypes_for_closing(self):
		if len(self.closed_documents) == 0:
			for doctype_for_closing in self.get_doctypes_for_closing():
				self.append('closed_documents', {
					"document_type": doctype_for_closing.document_type,
					"closed": doctype_for_closing.closed
				})


def get_closed_accounting_period(company, posting_date, voucher_type, cache=True):
	def generator():
		accounting_periods = frappe.db.sql_list("""
			SELECT ap.name
			FROM
				`tabAccounting Period` ap, `tabClosed Document` cd
			WHERE
				ap.name = cd.parent
				AND ap.company = %(company)s
				AND cd.closed = 1
				AND cd.document_type = %(voucher_type)s
				AND %(date)s between ap.start_date and ap.end_date
			""", {
				"company": company,
				"date": posting_date,
				"voucher_type": voucher_type
			}, as_dict=1)

		return accounting_periods[0] if accounting_periods else None

	if cache:
		cache_key = (company, posting_date, voucher_type)
		return frappe.local_cache("get_closed_accounting_period", cache_key, generator)
	else:
		return generator()


def on_doctype_update():
	frappe.db.add_index("Accounting Period", ["start_date", "end_date"])
