# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import erpnext
from frappe import _
from erpnext.controllers.status_updater import StatusUpdaterERP
from frappe.utils import flt, getdate, cint, validate_email_address, combine_datetime, now_datetime
from erpnext.accounts.party import get_party_bank_account, get_party_name
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry, get_company_defaults
from frappe.regional.regional import validate_mobile_no
from payments.utils import get_payment_gateway_controller


class PaymentRequest(StatusUpdaterERP):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.force_fields = [
			"currency",
			"payment_gateway",
			"payment_account",
			"expiry_date_allowed",
			"expiry_time_allowed",
		]

	def validate(self):
		self.set_missing_values()
		self.validate_reference_document()
		self.validate_payment_gateway()
		self.validate_payment_account()
		self.validate_amount()
		self.validate_contact()
		self.validate_expiry_date()
		self.set_status()

	def before_submit(self):
		self.request_payment_gateway_url()

	def on_submit(self):
		self.trigger_payment_request_notification()

	def before_cancel(self):
		self.check_if_payment_entry_exists()
		self.expire_payment_url()

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def on_payment_authorized(self, status, **kwargs):
		if not status:
			return

		args = frappe._dict(kwargs)
		if status in ["Authorized", "Completed"]:
			self.create_payment_entry(
				submit=True,
				reference_no=args.reference_no,
				reference_date=args.reference_date,
				amount=args.amount,
			)
			frappe.db.commit()
			self.create_sales_invoice()

	def set_status(self, update=False, status=None, update_modified=True):
		previous_status = self.status

		if self.docstatus == 0:
			self.status = "Draft"
		elif self.docstatus == 1:
			reference_doc = self.get_reference_document(reload=True)
			grand_total = flt(self.get_reference_document_grand_total(reference_doc),
				self.precision("grand_total"))
			outstanding_amount = flt(self.get_reference_document_outstanding_amount(reference_doc),
				self.precision("grand_total"))

			if outstanding_amount <= 0:
				self.status = "Paid"
			elif outstanding_amount < grand_total:
				self.status = "Partially Paid"
			else:
				if self.payment_request_type == "Inward":
					self.status = "Requested"
				elif self.payment_request_type == "Outward":
					payment_order = frappe.db.get_value("Payment Order Reference", {
						"payment_request": self.name, "docstatus": 1
					})
					if payment_order:
						self.status = "Payment Ordered"
					else:
						self.status = "Initiated"

		else:
			self.status = "Cancelled"

		self.add_status_comment(previous_status)

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

		if self.project and reference_doc.get("project") and self.project != reference_doc.get("project"):
			frappe.throw(_("{0} {1} in Payment Request does not match with {1} in Reference Document").format(
				_("Project"),
				frappe.bold(self.project),
				frappe.bold(reference_doc.project),
			))

	def validate_payment_gateway(self):
		if not self.payment_gateway_account:
			return

		doc = frappe.get_cached_doc("Payment Gateway Account", self.payment_gateway_account)

		if doc.currency != self.currency:
			frappe.throw(_("Payment Gateway Account Currency must be {0}").format(self.currency))

		if doc.company != self.company:
			frappe.throw(_("Company {0} in Payment Request does not match with Company {1} in Payment Gateway Account").format(
				frappe.bold(self.company),
				frappe.bold(doc.company),
			))

	@frappe.whitelist()
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
		if self.payment_request_type != "Inward":
			self.payment_gateway_account = None
			self.payment_gateway = None

		gateway_details = get_payment_gateway_account_details(self.payment_gateway_account)
		for k, v in gateway_details.items():
			if self.meta.has_field(k) and (not self.get(k) or k in self.force_fields):
				self.set(k, v)

	def validate_amount(self):
		reference_doc = self.get_reference_document()

		existing_payment_request = self.get_existing_payment_request_amount(
			self.reference_doctype,
			self.reference_name,
			exclude=self.name,
		)

		payment_request_total = flt(flt(self.grand_total) + existing_payment_request)
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

	def validate_contact(self):
		if not self.contact_mobile and not self.contact_email:
			frappe.throw(_("Either Contact Email or Contact Mobile is required"))

		if self.contact_email:
			validate_email_address(self.contact_email, throw=True)
		if self.contact_mobile:
			validate_mobile_no(self.contact_mobile, throw=True)

	def validate_expiry_date(self):
		if not self.expiry_date_allowed:
			self.expiry_date = None
		if not self.expiry_time_allowed:
			self.expiry_time = None

		if not self.expiry_date:
			self.expiry_time = None

		if self.expiry_date and self.expiry_time:
			expiry_dt = combine_datetime(self.expiry_date, self.expiry_time)
			if expiry_dt <= now_datetime():
				frappe.throw(_("Expiry Date/Time cannot be in the past"))
		elif self.expiry_date:
			if getdate(self.expiry_date) < getdate():
				frappe.throw(_("Expiry Date cannot be in the past"))

		if self.expiry_date and self.transaction_date:
			if getdate(self.expiry_date) < getdate(self.transaction_date):
				frappe.throw(_("Expiry Date cannot be before Request Date"))

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
		self.payment_url = None
		self.is_expired = 0

		if self.payment_request_type != "Inward":
			return
		if not self.payment_gateway or not self.payment_account:
			return

		payment_gateway_validation = self.payment_gateway_validation()
		if not payment_gateway_validation:
			return

		self.payment_url = self.get_payment_url()
		self.db_set({
			"payment_url": self.payment_url,
			"is_expired": 0,
		}, commit=True)

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
			"order_name": self.reference_name,
			"order_info": self.project,
			"amount": flt(self.grand_total, self.precision("grand_total")),
			"currency": self.currency,
			"description": self.subject,
			"payer_name": self.party_name or self.contact_display,
			"payer_email": self.contact_email,
			"payer_mobile": self.contact_mobile,
			"reference_doctype": self.doctype,
			"reference_docname": self.name,
			"expiry_date": self.get("expiry_date"),
			"expiry_time": self.get("expiry_time"),
		})

	def expire_payment_url(self):
		if self.payment_request_type != "Inward":
			return
		if not self.payment_gateway or not self.payment_url:
			return

		controller = get_payment_gateway_controller(self.payment_gateway)
		if not hasattr(controller, "expire_payment_url"):
			return False

		is_expired = controller.expire_payment_url(self.payment_url)
		if is_expired:
			self.db_set("is_expired", 1, commit=True)

		return is_expired

	def trigger_payment_request_notification(self):
		if self.mute_notification or self.flags.mute_notification:
			return
		if self.payment_request_type != "Inward":
			return
		if self.docstatus != 1 or self.status == "Paid":
			return

		self.run_method("notify_payment_request")
		if self.payment_url:
			self.run_method("notify_payment_url")

	def create_payment_entry(self, submit=False, reference_no=None, reference_date=None, amount=None):
		"""create entry"""
		frappe.flags.ignore_account_permission = True

		if amount is None:
			amount = self.grand_total

		amount = flt(amount)

		payment_entry = get_payment_entry(
			self.reference_doctype,
			self.reference_name,
			bank_amount=amount,
			bank_account=self.payment_account,
			mode_of_payment=self.mode_of_payment,
			is_advance=self.is_advance_payment(self.reference_doctype),
		)

		payment_entry.update({
			"reference_no": reference_no or self.name,
			"reference_date": getdate(reference_date),
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
				frappe.throw(_("Payment Entry is already submitted"), title=_('Error'))

	@classmethod
	def get_reference_document_details(cls, reference_doc, exclude=None):
		out = frappe._dict()
		if reference_doc.doctype not in cls.get_allowed_reference_doctypes():
			return out

		out.company = reference_doc.get("company")
		out.branch = reference_doc.get("branch")
		out.project = reference_doc.get("project")

		out.party_type, out.party, out.party_name = PaymentRequest.get_reference_document_party(reference_doc)

		out.contact_person = reference_doc.get("contact_person")
		out.contact_display = reference_doc.get("contact_display")
		out.contact_email = reference_doc.get("contact_email")
		out.contact_mobile = reference_doc.get("contact_mobile")

		out.grand_total = PaymentRequest.get_balance_payment_request_amount(reference_doc, exclude=exclude)
		out.currency = reference_doc.get("currency") or erpnext.get_default_currency()

		out.subject = _("Payment Request for {0}").format(reference_doc.get("reference_name"))

		return out

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
		existing_payment_request_amount = cls.get_existing_payment_request_amount(
			reference_doc.doctype,
			reference_doc.name,
			exclude=exclude,
		)
		outstanding_amount = cls.get_reference_document_outstanding_amount(reference_doc)

		return max(outstanding_amount - existing_payment_request_amount, 0)

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
	def get_existing_payment_request_amount(cls, reference_doctype, reference_name, exclude=None):
		exclude_condition = ""
		if exclude:
			exclude_condition = f" and name != {frappe.db.escape(exclude)}"

		existing_payment_request_amount = frappe.db.sql(f"""
			select sum(grand_total)
			from `tabPayment Request`
			where docstatus = 1
				and reference_doctype = %s
				and reference_name = %s
				{exclude_condition}
		""", (reference_doctype, reference_name))

		existing_payment_request_amount = flt(
			existing_payment_request_amount[0][0]) if existing_payment_request_amount else 0
		return existing_payment_request_amount

	@classmethod
	def get_reference_document_party(cls, reference_doc):
		return reference_doc.get_billing_party()

	@classmethod
	def is_advance_payment(cls, reference_doctype):
		if reference_doctype in ("Sales Order", "Proforma Invoice"):
			return True
		else:
			return False


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

	return frappe.db.get_value("Payment Gateway Account", filters)


@frappe.whitelist()
def get_payment_gateway_account_details(payment_gateway_account):
	doc = frappe.get_cached_doc("Payment Gateway Account", payment_gateway_account) if payment_gateway_account else frappe._dict()

	expiry_date_allowed = 0
	expiry_time_allowed = 0
	if doc.payment_gateway:
		try:
			controller = get_payment_gateway_controller(doc.payment_gateway)
			expiry_date_allowed = cint(getattr(controller, 'supports_expiry_date', False))
			expiry_time_allowed = cint(getattr(controller, 'supports_expiry_time', False))
		except Exception:
			pass

	if not expiry_date_allowed:
		expiry_time_allowed = 0

	return frappe._dict({
		"payment_gateway": doc.payment_gateway,
		"payment_account": doc.payment_account,
		"mode_of_payment": doc.mode_of_payment,
		"message": doc.message,
		"expiry_date_allowed": expiry_date_allowed,
		"expiry_time_allowed": expiry_time_allowed,
	})


@frappe.whitelist()
def get_reference_document_details(reference_doctype, reference_name, exclude=None):
	reference_doc = frappe.get_doc(reference_doctype, reference_name)
	return PaymentRequest.get_reference_document_details(reference_doc, exclude=exclude)


@frappe.whitelist()
def get_print_format_list(reference_doctype):
	print_format_list = ["Standard"]
	print_formats = frappe.get_all("Print Format", filters={"doc_type": reference_doctype, "disabled": 0})

	print_format_list.extend([p.name for p in print_formats])

	return {
		"print_format": print_format_list
	}


@frappe.whitelist()
def trigger_payment_request_notification(payment_request):
	doc = frappe.get_doc("Payment Request", payment_request)
	doc.check_permission("read")
	doc.trigger_payment_request_notification()


@frappe.whitelist()
def make_payment_entry(payment_request):
	doc = frappe.get_doc("Payment Request", payment_request)
	return doc.create_payment_entry(submit=False)


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
