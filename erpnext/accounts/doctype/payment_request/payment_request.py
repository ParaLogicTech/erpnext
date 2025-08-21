# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import erpnext
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate, cint
from erpnext.accounts.party import get_party_bank_account, get_party_name
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry, get_company_defaults
from payments.utils import get_payment_gateway_controller


class PaymentRequest(Document):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.force_fields = [
			'currency',
			'payment_gateway',
			'payment_account',
		]

	def validate(self):
		self.set_missing_values()
		self.validate_reference_document()
		self.validate_payment_gateway()
		self.validate_payment_account()
		self.validate_amount()
		self.set_status()

	def before_submit(self):
		self.request_payment_gateway_url()

	def on_submit(self):
		self.trigger_notifications()

	def before_cancel(self):
		self.check_if_payment_entry_exists()

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def on_payment_authorized(self, status=None):
		if not status:
			return

		if status in ["Authorized", "Completed"]:
			self.create_payment_entry(submit=True)
			frappe.db.commit()
			self.create_sales_invoice()

	def set_status(self, update=False, update_modified=True):
		if self.docstatus == 0:
			self.status = "Draft"
		elif self.docstatus == 1:
			if self.payment_request_type == "Outward":
				self.status = "Initiated"
			elif self.payment_request_type == "Inward":
				self.status = "Requested"
		else:
			self.status = "Cancelled"

		if update:
			self.db_set("status", self.status, update_modified=update_modified)

	def validate_reference_document(self):
		if not self.reference_doctype or not self.reference_name:
			frappe.throw(_("Reference Document is mandatory for Payment Request"))

		if self.reference_doctype not in self.get_allowed_reference_doctypes():
			frappe.throw(_("Reference Document Type {0} is not allowed").format(self.reference_doctype))

		reference_doc = self.get_reference_document()

		if reference_doc.docstatus != 1:
			frappe.throw(_("{0} is not submitted").format(frappe.get_desk_link(self.reference_doctype, self.reference_name)))

		if reference_doc.get("company") and self.company != reference_doc.get("company"):
			frappe.throw(_("Company {0} in Payment Request does not match with Company {1} in Reference Document").format(
				frappe.bold(self.company),
				frappe.bold(reference_doc.company),
			))

	def validate_payment_gateway(self):
		if self.payment_request_type == "Outward":
			self.payment_gateway_account = None
			self.payment_gateway = None

		if not self.payment_gateway_account:
			return

		doc = frappe.get_cached_doc("Payment Gateway Account")

		if doc.currency != self.currency:
			frappe.throw(_("Payment Gateway Account Currency must be {0}").format(self.currency))

		if doc.company != self.company:
			frappe.throw(_("Company {0} in Payment Request does not match with Company {1} in Payment Gateway Account").format(
				frappe.bold(self.company),
				frappe.bold(doc.company),
			))

	def set_missing_values(self):
		self.set_reference_document_details()
		self.set_payment_gateway_details()
		self.party_name = get_party_name(self.party_type, self.party)

	def set_reference_document_details(self):
		reference_doc = self.get_reference_document()
		reference_details = self.get_reference_document_details(reference_doc, exclude=self.name)

		for k, v in reference_details.items():
			if self.meta.has_field(k) and (not self.get(k) or k in self.force_fields):
				self.set(k, v)

	def set_payment_gateway_details(self):
		gateway_details = get_payment_gateway_account_details(self.payment_gateway_account)
		for k, v in gateway_details.items():
			if self.meta.has_field(k) and (not self.get(k) or k in self.force_fields):
				self.set(k, v)

	def validate_amount(self):
		reference_doc = self.get_reference_document()

		pending_payment_request = self.get_pending_payment_request_amount(
			self.reference_doctype,
			self.reference_name,
			exclude=self.name,
		)

		payment_request_total = flt(flt(self.grand_total) + pending_payment_request)
		grand_total = self.get_reference_document_grand_total(reference_doc)
		outstanding_amount = self.get_reference_document_outstanding_amount(reference_doc)

		if flt(payment_request_total, self.precision("grand_total")) > flt(grand_total, self.precision("grand_total")):
			frappe.throw(_("Total Payment Request Amount cannot be greater than the Grand Total {0} of {1}").format(
				frappe.format(grand_total, df=self.meta.get_field("grand_total")),
				frappe.get_desk_link(self.reference_doctype, self.reference_name),
			))

		if flt(payment_request_total, self.precision("grand_total")) > flt(outstanding_amount, self.precision("grand_total")):
			frappe.throw(_("Total Payment Request Amount cannot be greater than the Outstanding Amount {0} of {1}").format(
				frappe.format(outstanding_amount, df=self.meta.get_field("grand_total")),
				frappe.get_desk_link(self.reference_doctype, self.reference_name),
			))

	def get_reference_document(self, reload=False):
		if not self.get("reference_doc") or reload:
			if self.reference_doctype and self.reference_name:
				self.reference_doc = frappe.get_doc(self.reference_doctype, self.reference_name)
			else:
				self.reference_doc = frappe._dict()

		return self.reference_doc

	def validate_payment_account(self):
		if self.payment_account:
			payment_account_currency = frappe.db.get_value("Account", self.payment_account, "account_currency")
			if self.currency != payment_account_currency:
				frappe.throw(_("Payment Account Currency must be the same as Transaction Currency"))

	def request_payment_gateway_url(self):
		if self.payment_request_type != "Inward":
			return
		if not self.payment_gateway or not self.payment_account:
			return

		payment_gateway_validation = self.payment_gateway_validation()
		if not payment_gateway_validation:
			return

		self.payment_url = self.get_payment_url()
		if self.payment_url:
			self.db_set('payment_url', self.payment_url)

	def payment_gateway_validation(self):
		try:
			controller = get_payment_gateway_controller(self.payment_gateway)
			if hasattr(controller, 'on_payment_request_submission'):
				return controller.on_payment_request_submission(self)
			else:
				return True
		except Exception:
			return False

	def get_payment_url(self):
		controller = get_payment_gateway_controller(self.payment_gateway)
		controller.validate_transaction_currency(self.currency)

		if hasattr(controller, 'validate_minimum_transaction_amount'):
			controller.validate_minimum_transaction_amount(self.currency, self.grand_total)

		return controller.get_payment_url(**{
			"title": self.company,
			"order_id": self.name,
			"amount": flt(self.grand_total, self.precision("grand_total")),
			"currency": self.currency,
			"description": self.subject,
			"payer_name": self.party_name or self.contact_display,
			"payer_email": self.contact_email,
			"payer_mobile": self.contact_mobile,
			"reference_doctype": "Payment Request",
			"reference_docname": self.name,
		})

	def trigger_notifications(self):
		if self.mute_notification or self.flags.mute_notification:
			return
		if self.docstatus != 1:
			return

		if self.payment_url:
			self.run_method("notify_payment_url")

	def create_payment_entry(self, submit=False):
		"""create entry"""
		frappe.flags.ignore_account_permission = True

		payment_entry = get_payment_entry(
			self.reference_doctype,
			self.reference_name,
			party_amount=self.grand_total,
			bank_amount=self.grand_total,
			bank_account=self.payment_account,
			mode_of_payment=self.mode_of_payment,
		)

		payment_entry.update({
			"reference_no": self.name,
			"reference_date": nowdate(),
			"remarks": _("Payment Entry against {0} {1} via Payment Request {2}").format(
				self.reference_doctype,
				self.reference_name,
				self.name,
			),
			"payment_request": self.name,
		})

		if payment_entry.difference_amount:
			company_details = get_company_defaults(self.company)

			payment_entry.append("deductions", {
				"account": company_details.exchange_gain_loss_account,
				"cost_center": company_details.cost_center,
				"amount": payment_entry.difference_amount
			})

		if submit:
			payment_entry.flags.ignore_permissions = True
			payment_entry.insert()
			payment_entry.submit()
		else:
			payment_entry.run_method("set_missing_values")

		return payment_entry

	def create_sales_invoice(self):
		if not self.make_sales_invoice:
			return

		if self.reference_doctype == "Sales Order":
			from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
			sales_invoice = make_sales_invoice(self.reference_name, ignore_permissions=True)
		elif self.reference_doctype == "Proforma Invoice":
			from erpnext.accounts.doctype.proforma_invoice.proforma_invoice import make_sales_invoice
			sales_invoice = make_sales_invoice(self.reference_name, ignore_permissions=True)
		else:
			return

		sales_invoice.flags.ignore_permissions = True
		sales_invoice.set_advances(include_unallocated=False)
		sales_invoice.insert()
		sales_invoice.submit()

		return sales_invoice

	def check_if_payment_entry_exists(self):
		if self.status == "Paid":
			pref = frappe.get_all(
				"Payment Entry Reference",
				filters={
					"reference_doctype": self.reference_doctype,
					"reference_name": self.reference_name,
					"docstatus": ["<", 2]
				},
				fields=["parent"],
				limit=1
			)
			if pref:
				frappe.throw(_("Payment Entry already exists"), title=_('Error'))

	@classmethod
	def get_reference_document_details(cls, reference_doc, exclude=None):
		out = frappe._dict()
		if reference_doc.doctype not in cls.get_allowed_reference_doctypes():
			return out

		out.company = reference_doc.get("company")
		out.branch = reference_doc.get("branch")

		out.party_type, out.party, out.party_name = PaymentRequest.get_reference_document_party(reference_doc)

		out.contact_person = reference_doc.get("contact_person")
		out.contact_display = reference_doc.get("contact_display")
		out.contact_email = reference_doc.get("contact_email")
		out.contact_mobile = reference_doc.get("contact_mobile")
		out.contact_phone = reference_doc.get("contact_phone")

		out.grand_total = PaymentRequest.get_balance_payment_request_amount(reference_doc, exclude=exclude)
		out.currency = reference_doc.get("currency") or erpnext.get_default_currency()

		out.subject = _("Payment Request for {0}").format(reference_doc.get("reference_name"))

	@classmethod
	def get_allowed_reference_doctypes(cls):
		return [
			"Sales Order",
			"Purchase Order",
			"Sales Invoice",
			"Purchase Invoice",
			"Proforma Invoice",
		]

	@classmethod
	def get_balance_payment_request_amount(cls, reference_doc, exclude=None):
		pending_payment_request_amount = cls.get_pending_payment_request_amount(
			reference_doc.doctype,
			reference_doc.name,
			exclude=exclude,
		)
		outstanding_amount = cls.get_reference_document_outstanding_amount(reference_doc)

		return max(outstanding_amount - pending_payment_request_amount, 0)

	@classmethod
	def get_reference_document_outstanding_amount(cls, reference_doc):
		if reference_doc.meta.has_field("outstanding_amount"):
			return flt(reference_doc.get("outstanding_amount"))

		grand_total = cls.get_reference_document_grand_total(reference_doc)
		paid_amount = cls.get_reference_document_paid_amount(reference_doc)

		outstanding_amount = grand_total - paid_amount
		return outstanding_amount

	@classmethod
	def get_reference_document_paid_amount(cls, reference_doc):
		if reference_doc.meta.has_field("advance_paid"):
			return flt(reference_doc.get("advance_paid"))

		return 0

	@classmethod
	def get_reference_document_grand_total(cls, reference_doc):
		return flt(reference_doc.get("rounded_total") or reference_doc.get("grand_total"))

	@classmethod
	def get_pending_payment_request_amount(cls, reference_doctype, reference_name, exclude=None):
		exclude_condition = ""
		if exclude:
			exclude_condition = f" and name != {frappe.db.escape(exclude)}"

		pending_payment_request_amount = frappe.db.sql(f"""
			select sum(grand_total)
			from `tabPayment Request`
			where docstatus = 1
				and reference_doctype = %s
				and reference_name = %s
				and status != 'Paid'
				{exclude_condition}
		""", (reference_doctype, reference_name))

		pending_payment_request_amount = flt(
			pending_payment_request_amount[0][0]) if pending_payment_request_amount else 0
		return pending_payment_request_amount

	@classmethod
	def get_reference_document_party(cls, reference_doc):
		return reference_doc.get_billing_party()


@frappe.whitelist()
def make_payment_request(**args):
	"""Make payment request"""

	args = frappe._dict(args)

	reference_doctype = args.reference_doctype or args.dt
	reference_name = args.reference_name or args.dn

	if not reference_doctype or not reference_name:
		frappe.throw(_("Reference Document not provided"))
	if reference_doctype not in PaymentRequest.get_allowed_reference_doctypes():
		frappe.throw(_("Reference Document Type {0} is not allowed").format(reference_doctype))

	reference_doc = frappe.get_doc(reference_doctype, reference_name)

	payment_request_type = args.get("payment_request_type")
	if not payment_request_type:
		if reference_doctype in ("Purchase Order", "Purchase Invoice"):
			payment_request_type = "Outward"
		else:
			payment_request_type = "Inward"

	company = reference_doc.get("company") or erpnext.get_default_company()
	amount = PaymentRequest.get_balance_payment_request_amount(reference_doc)
	currency = reference_doc.get("currency") or erpnext.get_default_currency()

	if args.get("party_type") and args.get("party"):
		party_type = args.get("party_type")
		party = args.get("party")
	else:
		party_type, party, party_name = PaymentRequest.get_reference_document_party(reference_doc)

	payment_gateway_account = None
	if company and payment_request_type == "Inward":
		payment_gateway_account = get_payment_gateway_account(company, currency, args.get("payment_gateway"))

	bank_account = None
	if payment_request_type == "Outward" and party:
		bank_account = get_party_bank_account(party_type, party)

	preq_doc = frappe.new_doc("Payment Request")
	preq_doc.update({
		"company": company,
		"payment_request_type": payment_request_type,
		"reference_doctype": reference_doctype,
		"reference_name": reference_name,
		"grand_total": amount,
		"currency": currency,
		"contact_display": args.get("contact_display") or args.get("contact_name"),
		"contact_email": args.get("contact_email"),
		"contact_mobile": args.get("contact_mobile"),
		"contact_phone": args.get("contact_phone"),
		"subject": args.get("subject") or _("Payment Request for {0}").format(reference_name),
		"message": args.get("message"),
		"party_type": party_type,
		"party": party,
		"payment_gateway_account": payment_gateway_account,
		"bank_account": bank_account,
		"mute_notification": cint(args.get("mute_notification")),
	})

	preq_doc.run_method("set_missing_values")
	return preq_doc


def get_payment_gateway_account(company, currency, payment_gateway=None):
	filters = {
		"company": company,
		"currency": currency
	}

	if payment_gateway:
		filters["payment_gateway"] = payment_gateway
	else:
		filters["is_default"] = 1

	return frappe.db.get_value(
		"Payment Gateway Account",
		filters,
		as_dict=1,
	)


@frappe.whitelist()
def get_payment_gateway_account_details(payment_gateway_account):
	doc = frappe.get_cached_doc("Payment Gateway Account", payment_gateway_account) if payment_gateway_account else frappe._dict()
	return frappe._dict({
		"payment_gateway": doc.payment_gateway,
		"payment_account": doc.payment_account,
		"mode_of_payment": doc.mode_of_payment,
		"message": doc.message,
	})


@frappe.whitelist()
def get_reference_document_details(reference_doctype, reference_name, exclude=None):
	reference_doc = frappe.get_doc(reference_doctype, reference_name)
	return PaymentRequest.get_reference_document_details(reference_doc, exclude=exclude)


@frappe.whitelist()
def get_print_format_list(ref_doctype):
	print_format_list = ["Standard"]

	print_format_list.extend([p.name for p in frappe.get_all("Print Format",
		filters={"doc_type": ref_doctype})])

	return {
		"print_format": print_format_list
	}


@frappe.whitelist()
def resend_payment_notification(docname):
	return frappe.get_doc("Payment Request", docname).trigger_notifications()


@frappe.whitelist()
def make_payment_entry(docname):
	doc = frappe.get_doc("Payment Request", docname)
	return doc.create_payment_entry(submit=False)


def update_payment_req_status(doc):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_reference_details

	for ref in doc.references:
		payment_request_name = frappe.db.get_value("Payment Request",
			{"reference_doctype": ref.reference_doctype, "reference_name": ref.reference_name,
			"docstatus": 1})

		if payment_request_name:
			ref_details = get_reference_details(
				ref.reference_doctype,
				ref.reference_name,
				doc.party_account_currency,
				doc.party_type,
				doc.party,
				doc.paid_from if doc.payment_type == "Receive" else doc.paid_to,
				doc.payment_type
			)
			pay_req_doc = frappe.get_doc('Payment Request', payment_request_name)
			status = pay_req_doc.status

			if status != "Paid" and not ref_details.outstanding_amount:
				status = 'Paid'
			elif status != "Partially Paid" and ref_details.outstanding_amount != ref_details.total_amount:
				status = 'Partially Paid'
			elif ref_details.outstanding_amount == ref_details.total_amount:
				if pay_req_doc.payment_request_type == 'Outward':
					status = 'Initiated'
				elif pay_req_doc.payment_request_type == 'Inward':
					status = 'Requested'

			pay_req_doc.db_set('status', status)
			frappe.db.commit()


@frappe.whitelist()
def make_payment_order(source_name, target_doc=None):
	from frappe.model.mapper import get_mapped_doc

	def set_missing_values(source, target):
		target.payment_order_type = "Payment Request"
		target.append('references', {
			'reference_doctype': source.reference_doctype,
			'reference_name': source.reference_name,
			'amount': source.grand_total,
			'supplier': source.party,
			'payment_request': source_name,
			'mode_of_payment': source.mode_of_payment,
			'bank_account': source.bank_account,
			'account': source.account
		})

	doclist = get_mapped_doc("Payment Request", source_name,	{
		"Payment Request": {
			"doctype": "Payment Order",
		}
	}, target_doc, set_missing_values)

	return doclist
