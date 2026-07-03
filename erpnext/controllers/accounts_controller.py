# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
import erpnext
from frappe import _, scrub
from frappe.utils import (
	today,
	flt,
	formatdate,
	cstr,
	date_diff,
	getdate,
	nowdate,
	clean_whitespace,
	cint,
)
from erpnext.accounts.utils import get_fiscal_years, validate_fiscal_year, get_account_currency
from erpnext.utilities.transaction_base import TransactionBase
from erpnext.accounts.party import get_party_account_currency, validate_party_frozen_disabled, get_party_account
from erpnext.exceptions import InvalidCurrency
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions
from erpnext.accounts.doctype.payment_terms_template.payment_terms_template import (
	get_payment_term_due_date,
	get_payment_terms,
	get_due_date_from_template,
)
from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import (
	get_unreconciled_journal_entries,
	get_unreconciled_payment_entries,
	get_unreconciled_dr_cr_notes,
	reconcile_payments_against_invoices,
	unlink_voucher_from_payments,
	calculate_difference_amount,
)
from collections import OrderedDict
import json


class AccountsController(TransactionBase):
	def __init__(self, *args, **kwargs):
		super(AccountsController, self).__init__(*args, **kwargs)

	@property
	def company_currency(self):
		if not hasattr(self, "__company_currency"):
			self.__company_currency = erpnext.get_company_currency(self.company)

		return self.__company_currency

	@property
	def company_abbr(self):
		if not hasattr(self, "_abbr"):
			self._abbr = frappe.db.get_value('Company',  self.company,  "abbr")

		return self._abbr

	def onload(self):
		self.set_onload("make_payment_via_journal_entry",
			frappe.db.get_single_value('Accounts Settings', 'make_payment_via_journal_entry'))

		if self.docstatus == 0:
			self.set_missing_values(for_validate=True)

	def before_print(self, print_settings=None):
		self.company_address_doc = erpnext.get_company_address_doc(self)

		if self.doctype in ['Journal Entry', 'Payment Entry']:
			self.get_gl_entries_for_print()
			self.get_party_to_party_name_dict()

	def validate(self):
		if self.get("_action") and self._action != "update_after_submit":
			self.set_missing_values(for_validate=True)

		self.validate_date_with_fiscal_year()
		self.validate_party()
		self.ensure_supplier_is_not_blocked()
		self.validate_currency()
		self.clean_remarks()

		validate_regional(self)

	def set_missing_values(self, for_validate=False):
		if frappe.flags.in_test:
			for fieldname in ["posting_date", "transaction_date"]:
				if self.meta.get_field(fieldname) and not self.get(fieldname):
					self.set(fieldname, today())
					break

	def validate_date_with_fiscal_year(self):
		if self.meta.get_field("fiscal_year"):
			date_field = ""
			if self.meta.get_field("posting_date"):
				date_field = "posting_date"
			elif self.meta.get_field("transaction_date"):
				date_field = "transaction_date"

			if date_field and self.get(date_field):
				validate_fiscal_year(self.get(date_field), self.fiscal_year, self.company, self.meta.get_label(date_field), self)

	def clean_remarks(self):
		fields = [
			'remarks', 'remark', 'user_remark', 'user_remarks',
			'cheque_no', 'reference_no',
			'po_no', 'supplier_delivery_note', 'lr_no'
		]
		for f in fields:
			if self.meta.has_field(f):
				self.set(f, clean_whitespace(self.get(f)))

	def validate_party(self):
		party_type, party, party_name = self.get_party()
		validate_party_frozen_disabled(party_type, party)

		billing_party_type, billing_party, party_name = self.get_billing_party()
		if (billing_party_type, billing_party) != (party_type, party):
			validate_party_frozen_disabled(billing_party_type, billing_party)

	def get_party(self):
		if self.meta.has_field("party_type") and self.meta.has_field("party"):
			return self.get("party_type"), self.get("party"), self.get("party_name")
		else:
			party_type = None
			if self.meta.get_field("customer"):
				party_type = "Customer"
			elif self.meta.get_field("supplier"):
				party_type = "Supplier"

			party = self.get(scrub(party_type)) if party_type else None
			party_name = self.get(scrub(party_type) + "_name") if party else None
			return party_type, party, party_name

	def get_billing_party(self):
		return self.get_party()

	def get_party_account(self):
		return None

	def get_party_account_for_payment(self, fallback_default_account=True):
		party_account = self.get_party_account()
		if not party_account and fallback_default_account:
			party_type, party, party_name = self.get_billing_party()
			party_account = get_party_account(party_type, party, self.company, transaction_type=self.get("transaction_type"))

		return party_account

	def get_reference_details_for_payment(self, party_type, party, account, payment_type):
		return {}

	def ensure_supplier_is_not_blocked(self, is_payment=False, supplier=None):
		if not supplier:
			if self.get("party") and self.get("party_type") == "Supplier":
				supplier = self.get("party")
			else:
				supplier = self.get("supplier")

		if not supplier:
			return

		supplier_doc = frappe.get_cached_doc("Supplier", supplier)
		if supplier_doc.on_hold and (
			(not is_payment and supplier_doc.hold_type in ['All', 'Invoices'])
			or (is_payment and supplier_doc.hold_type in ['All', 'Payments'])
		):
			if not supplier_doc.release_date or getdate(nowdate()) <= getdate(supplier_doc.release_date):
				frappe.throw(_("{0} is blocked so this transaction cannot proceed").format(
					frappe.get_desk_link("Supplier", supplier)
				))

	def validate_currency(self):
		if not self.get("currency"):
			return

		party_type, party, party_name = self.get_billing_party()
		if party_type and party:
			party_account_currency = get_party_account_currency(party_type, party, self.company)

			if (
				party_account_currency
				and party_account_currency != self.company_currency
				and self.currency != party_account_currency
			):
				frappe.throw(_("Accounting Entry for {0}: {1} can only be made in currency: {2}").format(
					party_type, party, party_account_currency
				), InvalidCurrency)

	def validate_payment_schedule(self):
		if not self.meta.has_field("payment_schedule"):
			return

		self.set_payment_schedule()
		self.validate_payment_schedule_dates()
		self.validate_payment_schedule_amount()

		if self.meta.has_field("due_date"):
			self.set_due_date()
			self.validate_due_date()

	def set_payment_schedule(self, exclude_bill_date=False):
		if self.get("is_pos") or self.get("is_return"):
			self.payment_terms_template = None
			self.payment_schedule = []
			return

		posting_date = self.get("posting_date") or self.get("transaction_date")
		bill_date = self.get("bill_date") if not exclude_bill_date else None
		due_date = self.get("due_date") or posting_date
		delivery_date = self.get("delivery_date") or self.get("schedule_date")

		payable_amount = self.get_payable_amount()
		remaining_amount = payable_amount

		if not self.get("payment_schedule"):
			if self.get("payment_terms_template"):
				data = get_payment_terms(self.payment_terms_template, posting_date=posting_date,
					delivery_date=delivery_date, bill_date=bill_date, grand_total=payable_amount)
				for item in data:
					self.append("payment_schedule", item)
			else:
				self.append("payment_schedule", {
					"due_date": due_date,
					"invoice_portion": 100,
					"payment_amount": payable_amount,
					"payment_amount_type": "Percentage"
				})
		else:
			for d in self.get("payment_schedule"):
				if d.payment_term:
					term = frappe.get_cached_doc("Payment Term", d.payment_term)
					d.due_date = get_payment_term_due_date(term, posting_date, bill_date=bill_date, delivery_date=delivery_date)

				if getdate(d.due_date) < getdate(posting_date):
					d.due_date = posting_date

		for d in self.get("payment_schedule"):
			if d.payment_amount_type == "Remaining Amount":
				d.payment_amount = flt(remaining_amount, d.precision('payment_amount'))
			elif d.payment_amount_type == "Amount":
				term_payment_amount = frappe.get_cached_value("Payment Term", d.payment_term, "payment_amount")\
					if d.payment_term else 0
				payment_amount = flt(term_payment_amount or d.payment_amount)
				d.payment_amount = flt(min(payment_amount, payable_amount), d.precision('payment_amount'))
			else:
				d.payment_amount = flt(payable_amount * flt(d.invoice_portion) / 100, d.precision('payment_amount'))

			remaining_amount -= d.payment_amount

			if d.payment_amount_type in ("Amount", "Remaining Amount"):
				d.invoice_portion = flt(d.payment_amount / payable_amount * 100) if payable_amount else 0

	def validate_payment_schedule_dates(self):
		if self.get("is_pos") or self.get("is_return"):
			return

		dates = []
		li = []

		for d in self.get("payment_schedule"):
			if self.get("transaction_date") and getdate(d.due_date) < getdate(self.transaction_date):
				frappe.throw(_("Row {0}: Due Date in the Payment Terms table cannot be before Transaction Date").format(d.idx))
			if d.due_date in dates:
				li.append(_("{0} in row {1}").format(frappe.format(getdate(d.due_date)), d.idx))
			dates.append(d.due_date)

		if li:
			duplicates = '<br>' + '<br>'.join(li)
			frappe.msgprint(_("Payment Schedule rows with duplicate Due Dates found: {0}").format(duplicates),
				alert=True, indicator='orange')

	def validate_payment_schedule_amount(self):
		if self.get("is_pos") or self.get("is_return"):
			return

		if self.get("payment_schedule"):
			payment_schedule_precision = self.precision("payment_amount", "payment_schedule")

			payment_schedule_total = sum([d.payment_amount for d in self.get("payment_schedule")])
			payment_schedule_total = flt(payment_schedule_total, payment_schedule_precision)

			payable_amount = self.get_payable_amount()
			payable_amount = flt(payable_amount, payment_schedule_precision)

			if payment_schedule_total != payable_amount:
				frappe.throw(_("Total Payment Amount in Payment Schedule must be equal to Grand / Rounded Total"))

	def get_payable_amount(self):
		grand_total = flt(self.get("rounded_total") or self.get("grand_total"))

		if self.get("write_off_amount"):
			grand_total -= flt(self.write_off_amount)

		if self.get("total_advance"):
			grand_total -= flt(self.get("total_advance"))

		if self.get("prepaid_deferred_revenue"):
			grand_total -= flt(self.get("prepaid_deferred_revenue"))

		return grand_total

	def set_due_date(self):
		due_dates = [getdate(d.due_date) for d in self.get("payment_schedule") if d.due_date]
		if due_dates:
			self.due_date = max(due_dates)

	def validate_due_date(self, exclude_bill_date=False):
		if self.get('is_pos'):
			return
		if not self.meta.has_field("due_date"):
			return

		posting_date = self.get("posting_date") or self.get("transaction_date")
		bill_date = self.get("bill_date") if not exclude_bill_date else None
		delivery_date = self.get("delivery_date") or self.get("schedule_date")

		if not self.due_date:
			frappe.throw(_("Due Date is mandatory"))
		if getdate(self.due_date) < getdate(bill_date or posting_date):
			frappe.throw(_("Due Date cannot be before Posting / Supplier Invoice Date"))

		if self.get("payment_terms_template"):
			default_due_date = get_due_date_from_template(self.payment_terms_template, posting_date=posting_date,
				bill_date=bill_date, delivery_date=delivery_date)
			if not default_due_date:
				return

			if default_due_date != posting_date and getdate(self.due_date) > getdate(default_due_date):
				is_credit_controller = frappe.db.get_single_value("Accounts Settings", "credit_controller") in frappe.get_roles()
				if is_credit_controller:
					frappe.msgprint(_("Note: Due Date exceeds allowed customer credit days by {0} day(s)").format(
						date_diff(self.due_date, default_due_date)
					))
				else:
					frappe.throw(_("Due Date cannot be after {0} for Payment Terms Template {1}").format(
						formatdate(default_due_date), self.payment_terms_template
					))

	def get_gl_dict(self, args, account_currency=None, item=None):
		"""this method populates the common properties of a gl entry record"""

		posting_date = args.get('posting_date') or self.get('posting_date')
		fiscal_years = get_fiscal_years(posting_date, company=self.company)
		if len(fiscal_years) > 1:
			frappe.throw(_("Multiple fiscal years exist for the date {0}. Please set company in Fiscal Year").format(
				formatdate(posting_date)))
		else:
			fiscal_year = fiscal_years[0][0]

		gl_dict = frappe._dict({
			'company': self.company,
			'posting_date': posting_date,
			'fiscal_year': fiscal_year,
			'voucher_type': self.doctype,
			'voucher_no': self.name,
			'remarks': self.get("remarks") or self.get("remark"),
			'debit': 0,
			'credit': 0,
			'debit_in_account_currency': 0,
			'credit_in_account_currency': 0,
			'is_opening': self.get("is_opening") or "No",
			'party_type': None,
			'party': None,
			'project': item and item.get("project") or self.get("project"),
			'cost_center': item and item.get("cost_center") or self.get("cost_center"),
			'reference_no': self.get("reference_no") or self.get("cheque_no") or self.get("bill_no"),
			'reference_date': self.get("reference_date") or self.get("cheque_date") or self.get("bill_date")
		})

		accounting_dimensions = get_accounting_dimensions(as_list=False)
		dimension_dict = frappe._dict()

		for dimension in accounting_dimensions:
			dimension_dict[dimension.fieldname] = self.get(dimension.fieldname)
			if item and item.get(dimension.fieldname):
				dimension_dict[dimension.fieldname] = item.get(dimension.fieldname)

			if not args.get(dimension.fieldname) and args.get('party') and args.get('party_type') == dimension.document_type:
				dimension_dict[dimension.fieldname] = args.get('party')

		gl_dict.update(dimension_dict)
		gl_dict.update(args)

		if not account_currency:
			account_currency = get_account_currency(gl_dict.account)

		if gl_dict.account and self.doctype not in ["Journal Entry", "Period Closing Voucher", "Payment Entry"]:
			self.validate_account_currency(gl_dict.account, account_currency)
			set_balance_in_account_currency(gl_dict, account_currency, self.get("conversion_rate"), self.company_currency)

		return gl_dict

	def validate_account_currency(self, account, account_currency=None):
		valid_currency = [self.company_currency]
		if self.get("currency") and self.currency != self.company_currency:
			valid_currency.append(self.currency)

		if account_currency not in valid_currency:
			frappe.throw(_("Account {0} is invalid. Account Currency must be {1}").format(
				account, _(" or ").join(valid_currency)
			))

	def unlink_payments_on_invoice_cancel(self):
		if not self.get("is_return"):
			unlink_voucher_from_payments(self.doctype, self.name, True)

	def unlink_payments_on_order_cancel(self):
		if frappe.db.get_single_value('Accounts Settings', 'unlink_advance_payment_on_cancelation_of_order'):
			unlink_voucher_from_payments(self.doctype, self.name, True)

	@frappe.whitelist()
	def set_advances(self, include_unallocated=True, against_project=None):
		"""Returns list of advances against Account, Party, Reference"""
		self.set("advances", [])
		if self.get("is_return"):
			return

		include_unallocated = cint(include_unallocated)
		res = self.get_advance_entries(include_unallocated=include_unallocated, against_project=against_project)
		company_currency = erpnext.get_company_currency(self.company)

		total_advance_allocated = 0
		if self.get("party_account_currency") and self.get("party_account_currency") == company_currency:
			grand_total = self.get("base_rounded_total") or self.get("base_grand_total")
		else:
			grand_total = self.get("rounded_total") or self.get("grand_total")

		for d in res:
			row = self.append("advances", {
				"reference_type": d.reference_type,
				"reference_name": d.reference_name,
				"reference_row": d.reference_row,
				"remarks": d.remarks,
				"advance_amount": flt(d.amount),
				"paid_amount": flt(d.total_paid_amount) or flt(d.amount),
				"exchange_rate": flt(d.exchange_rate) or 1
			})

			remaining_amount = flt(grand_total) - total_advance_allocated

			advance_total = flt(row.advance_amount)
			if row.meta.has_field("advance_tax"):
				advance_total += flt(d.advance_tax)
				advance_total = flt(advance_total, self.precision("total_advance"))

				row.advance_total = advance_total
				row.advance_tax = flt(row.advance_total - row.advance_amount, self.precision("total_advance"))

			allocated_amount = flt(min(remaining_amount, advance_total), self.precision('total_advance'))
			row.allocated_amount = allocated_amount

			total_advance_allocated += flt(allocated_amount)

		advance_doctype = self.meta.get_options("advances")
		if frappe.get_meta(advance_doctype).has_field("advance_tax_detail"):
			self.set_advance_tax_amounts()

	def set_advance_tax_amounts(self):
		payment_entries = list(set([d.reference_name for d in self.advances if d.reference_type == "Payment Entry"]))
		advance_tax_map = self.get_advance_tax_map(payment_entries)

		for d in self.advances:
			if d.reference_type == "Payment Entry":
				d.advance_tax_detail = json.dumps(advance_tax_map.get(d.reference_name)) if advance_tax_map.get(d.reference_name) else None

	def get_advance_tax_map(self, payment_entries):
		advance_tax_map = {}
		if payment_entries:
			advance_tax_data = frappe.db.sql("""
				select parent as payment_entry, account_head, tax_amount
				from `tabAdvance Taxes and Charges`
				where parent in %s
			""", [payment_entries], as_dict=1)

			for d in advance_tax_data:
				advance_tax_map.setdefault(d.payment_entry, {}).setdefault(d.account_head, 0)
				advance_tax_map[d.payment_entry][d.account_head] += d.tax_amount

		return advance_tax_map

	def get_advance_tax_allocated(self):
		advance_tax_allocated = 0

		payment_entry_data = frappe.db.sql("""
			select
				pe.name as payment_entry,
				sum(pref.allocated_amount) as allocated_amount,
				if(pe.payment_type = 'Receive', pe.paid_amount_before_tax, pe.received_amount_before_tax) as total_paid_amount
			from `tabPayment Entry Reference` pref
			inner join `tabPayment Entry` pe on pe.name = pref.parent
			where pref.docstatus = 1 and (
				(pref.reference_doctype = %(doctype)s and pref.reference_name = %(name)s)
				or (pref.original_reference_doctype = %(doctype)s and pref.original_reference_name = %(name)s)
			)
			group by pe.name
		""", {"doctype": self.doctype, "name": self.name}, as_dict=True)

		payment_entries = list(set(d.payment_entry for d in payment_entry_data))
		payment_entry_map = {}
		for d in payment_entry_data:
			payment_entry_map[d.payment_entry] = d

		advance_tax_map = self.get_advance_tax_map(payment_entries)
		for payment_entry, advance_tax_accounts in advance_tax_map.items():
			pe_details = payment_entry_map[payment_entry]
			for tax_account, tax_amount in advance_tax_accounts.items():
				tax = [tax for tax in self.get("taxes") if tax.account_head == tax_account]
				tax = tax[0] if tax else None
				if not tax:
					continue

				allocated_tax = tax_amount * pe_details.allocated_amount / pe_details.total_paid_amount if pe_details.total_paid_amount else 0
				advance_tax_allocated += allocated_tax

		return flt(advance_tax_allocated, self.precision("advance_paid"))

	def clear_unallocated_advances(self, parentfield="advances"):
		self.set(parentfield, self.get(parentfield, {"allocated_amount": ["not in", [0, None, ""]]}))
		for i, d in enumerate(self.get(parentfield)):
			d.idx = i + 1

	def get_advance_entries(self, include_unallocated=True, against_project=None):
		party_account = self.get_party_account()
		party_type, party, party_name = self.get_billing_party()
		order_list = self.get_orders_for_advance_entries()

		if not party_account or not party_type or not party:
			return []

		journal_entries = get_unreconciled_journal_entries(
			party_type,
			party,
			party_account,
			order_list=order_list,
			include_unallocated=include_unallocated,
			against_all_orders=False,
			against_project=against_project,
		)

		payment_entries = get_unreconciled_payment_entries(
			party_type,
			party,
			party_account,
			order_list=order_list,
			include_unallocated=include_unallocated,
			against_all_orders=False,
			against_project=against_project,
		)

		dr_cr_notes = get_unreconciled_dr_cr_notes(
			party_type,
			party,
			party_account,
			order_list=order_list,
			include_unallocated=include_unallocated,
			against_project=against_project,
		)

		all_entries = sorted(journal_entries + payment_entries, key=lambda d: (not bool(d.against_order), d.posting_date))
		all_entries += dr_cr_notes

		return all_entries

	def get_orders_for_advance_entries(self):
		return []

	def validate_total_advance_amount(self):
		grand_total = self.rounded_total or self.grand_total

		if self.party_account_currency == self.currency:
			invoice_total = flt(
				grand_total - flt(self.get("write_off_amount")) - flt(self.get("prepaid_deferred_revenue")),
				self.precision("grand_total")
			)
		else:
			base_write_off_amount = flt(
				flt(self.get("write_off_amount")) * self.conversion_rate,
				self.precision("base_write_off_amount")
			)
			invoice_total = flt(
				(grand_total * self.conversion_rate) - base_write_off_amount - flt(self.get("prepaid_deferred_revenue")),
				self.precision("grand_total")
			)

		if invoice_total > 0 and self.total_advance > invoice_total:
			frappe.throw(_("Total Advance amount cannot be greater than {0} {1}").format(
				self.party_account_currency,
				frappe.format(invoice_total, df=self.meta.get_field("total_advance"), doc=self)
			))

	def check_advance_payment_against_order(self):
		if self.get("is_return"):
			return

		order_list = self.get_orders_for_advance_entries()
		if not order_list:
			return

		advance_entries = self.get_advance_entries(
			include_unallocated=True if self.get("project") else False,
			against_project=self.get("project")
		)
		if advance_entries:
			advance_entries_against_si = [d.reference_name for d in self.get("advances")]
			for d in advance_entries:
				if not advance_entries_against_si or d.reference_name not in advance_entries_against_si:
					against_document_type = d.against_order_doctype
					against_document = d.against_order
					if not d.against_order and d.project:
						against_document_type = "Project"
						against_document = d.project

					frappe.msgprint(_("Unreconciled {0} is allocated against {1} {2}, check if it should be pulled as an advance in this invoice.").format(
						frappe.get_desk_link(d.reference_type, d.reference_name),
						_(against_document_type),
						frappe.bold(against_document),
					))

	def reconcile_advance_payments(self):
		"""
			Links invoice and advance voucher:
				1. cancel advance voucher
				2. split into multiple rows if partially adjusted, assign against voucher
				3. submit advance voucher
		"""

		party_type, party, party_name = self.get_billing_party()
		party_account = self.get_party_account()
		account_currency = get_account_currency(party_account)
		if not party_type or not party or not party_account:
			return

		party_account_type = erpnext.get_party_account_type(party_type)
		payment_type = "Receive" if party_account_type == "Receivable" else "Pay"

		payment_reference_details = self.get_reference_details_for_payment(party_type, party, party_account, payment_type)
		invoice_amounts = {
			"grand_total": flt(payment_reference_details.get("total_amount")),
			"exchange_rate": flt(payment_reference_details.get("exchange_rate")) or 1,
			"outstanding_amount": flt(payment_reference_details.get("outstanding_amount"))
		}

		reconciliation_list = []
		for d in self.get("advances"):
			if flt(d.allocated_amount) <= 0:
				continue
			if d.reference_type == "Employee Advance":
				continue

			allocated_amount = flt(d.allocated_amount)
			if flt(d.get("allocated_tax")):
				allocated_amount = flt(allocated_amount - flt(d.get("allocated_tax")), 9)

			reconciliation_args = frappe._dict({
				"voucher_type": d.reference_type,
				"voucher_no": d.reference_name,
				"voucher_detail_no": d.reference_row,
				"against_voucher_type": self.doctype,
				"against_voucher": self.name,
				"account": party_account,
				"party_type": party_type,
				"party": party,
				"unreconciled_amount": flt(d.advance_amount),
				"allocated_amount": allocated_amount,
				"currency": account_currency,
				"payment_exchange_rate": flt(d.get("exchange_rate")) or 1,
				"reconciliation_posting_date": self.get("posting_date") or self.get("transaction_date"),
			})
			reconciliation_args.update(invoice_amounts)
			reconciliation_args["difference_amount"] = calculate_difference_amount(reconciliation_args)
			reconciliation_list.append(reconciliation_args)

		if reconciliation_list:
			# Workaround for outstanding amount validation in JV and PE
			# Outstanding amount should be outstanding before advance allocation
			self.run_method("set_outstanding_amount", update=True)

			reconcile_payments_against_invoices(reconciliation_list)

	def get_company_default(self, fieldname):
		from erpnext.accounts.utils import get_company_default
		return get_company_default(self.company, fieldname)

	def unlink_advance_entries(self, reference_type, reference_name, validate_permissions=False):
		if not can_unlink_advances_from_doctype(self.doctype, validate_permissions=validate_permissions):
			return

		total_advance = flt(self.get("total_advance"))

		to_remove = []
		for adv in self.advances:
			if adv.reference_type == reference_type and adv.reference_name == reference_name:
				if flt(adv.get("allocated_tax")):
					continue
				to_remove.append(adv)

		if not to_remove:
			return

		for adv in to_remove:
			total_advance -= flt(adv.get("allocated_amount"))
			self.remove(adv)

		self.update_child_table("advances")

		total_advance = flt(total_advance, self.precision("total_advance"))
		self.db_set("total_advance", total_advance, notify=True)

	def get_gl_entries_for_print(self):
		from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions
		dimension_fields = get_accounting_dimensions()

		if self.docstatus == 1:
			gles = frappe.get_all(
				"GL Entry",
				filters={
					"voucher_type": self.doctype, "voucher_no": self.name
				},
				fields=[
					'account', 'remarks', 'party_type', 'party', 'debit', 'credit',
					'against_voucher', 'against_voucher_type', 'reference_no', 'reference_date'
				] + dimension_fields,
				order_by="creation"
			)
		else:
			gles = self.get_gl_entries()

		grouped_gles = OrderedDict()

		for gle in gles:
			key = [gle.account, cstr(gle.party_type), cstr(gle.party), cstr(gle.remarks), cstr(gle.reference_no),
				cstr(gle.reference_date), bool(gle.against_voucher)]
			key += [cstr(gle.get(f)) for f in dimension_fields]
			key = tuple(key)
			group = grouped_gles.setdefault(key, frappe._dict({
				"account": cstr(gle.account),
				"party_type": cstr(gle.party_type),
				"party": cstr(gle.party),
				"remarks": cstr(gle.remarks),
				"reference_no": cstr(gle.reference_no),
				"reference_date": cstr(gle.reference_date),
				"sum": 0, "against_voucher_set": set(), "against_voucher": []
			}))
			for f in dimension_fields:
				group[f] = cstr(gle.get(f))
			group.sum += flt(gle.debit) - flt(gle.credit)
			if gle.against_voucher_type and gle.against_voucher:
				group.against_voucher_set.add((cstr(gle.against_voucher_type), cstr(gle.against_voucher)))

		for d in grouped_gles.values():
			d.debit = d.sum if d.sum > 0 else 0
			d.credit = -d.sum if d.sum < 0 else 0

			for against_voucher_type, against_voucher in d.against_voucher_set:
				bill_no = None
				if against_voucher_type in ['Journal Entry', 'Purchase Invoice']:
					bill_no = frappe.db.get_value(against_voucher_type, against_voucher, 'bill_no')

				if bill_no:
					d.against_voucher.append(bill_no)
				else:
					d.against_voucher.append(frappe.utils.get_original_name(against_voucher_type, against_voucher))

			d.against_voucher = ", ".join(d.against_voucher or [])

		self.gl_entries = list(grouped_gles.values())
		self.total_debit = sum([d.debit for d in self.gl_entries])
		self.total_credit = sum([d.credit for d in self.gl_entries])

	def get_party_to_party_name_dict(self):
		self.party_to_party_name = {}
		if self.doctype == "Payment Entry":
			self.party_to_party_name[(self.party_type, self.party)] = self.party_name
		if self.doctype == "Journal Entry":
			for d in self.accounts:
				if d.party_type and d.party and d.party_name:
					self.party_to_party_name[(d.party_type, d.party)] = d.party_name

	def validate_deferred_start_and_end_date(self):
		if self.get("is_return"):
			return

		for d in self.items:
			if d.get("enable_deferred_revenue") or d.get("enable_deferred_expense"):
				if not (d.service_start_date and d.service_end_date):
					frappe.throw(_("Row #{0}: Service Start and End Date is required for deferred accounting").format(d.idx))
				elif getdate(d.service_start_date) > getdate(d.service_end_date):
					frappe.throw(_("Row #{0}: Service Start Date cannot be greater than Service End Date").format(d.idx))
				elif getdate(self.posting_date) > getdate(d.service_end_date):
					frappe.throw(_("Row #{0}: Service End Date cannot be before Invoice Posting Date").format(d.idx))

	def set_cashier(self, force=False):
		if cint(self.get("is_pos")):
			if not self.cashier or force:
				self.cashier = frappe.flags.current_cashier or frappe.session.user or self.owner
		else:
			self.cashier = None

	def validate_pos_is_open(self, throw=True):
		from erpnext.accounts.doctype.pos_profile.pos_profile import check_is_pos_open
		if self.is_pos and self.pos_profile:
			user = self.cashier or self.owner
			check_is_pos_open(user, self.pos_profile, self.get("posting_date") or self.get("transaction_date"), throw=throw)


def has_advance_entry_reference_to_unlink(
	invoice_type,
	invoice_no,
	reference_type,
	reference_name,
	validate_permissions=False,
):
	if not can_unlink_advances_from_doctype(invoice_type, validate_permissions=validate_permissions):
		return False

	advances_df = frappe.get_meta(invoice_type).get_field("advances")
	child_doctype = advances_df.options

	return frappe.db.exists(child_doctype, {
		"parenttype": invoice_type,
		"parent": invoice_no,
		"reference_type": reference_type,
		"reference_name": reference_name,
		"docstatus": ["<", 2],
	})


def can_unlink_advances_from_doctype(doctype, validate_permissions=False):
	meta = frappe.get_meta(doctype)
	advances_df = meta.get_field("advances")
	if not advances_df or advances_df.fieldtype != "Table" or not advances_df.options:
		return False

	try:
		from frappe.model.base_document import get_controller
		if not hasattr(get_controller(doctype), "unlink_advance_entries"):
			return False

		if not getattr(get_controller(doctype), "allow_advances_unlink", False):
			return False
	except ImportError:
		return False

	if validate_permissions:
		allow_unlink_setting = cint(
			frappe.db.get_single_value("Accounts Settings", "unlink_advance_on_cancellation_of_payment")
		)
		allow_unlink_role = frappe.db.get_single_value("Accounts Settings", "restrict_unlink_payments_to_role")
		has_unlink_role_permission = not allow_unlink_role or allow_unlink_role in frappe.get_roles()
		if not allow_unlink_setting or not has_unlink_role_permission:
			return False

	return True


def validate_conversion_rate(currency, conversion_rate, conversion_rate_label, company):
	"""common validation for currency and price list currency"""

	company_currency = frappe.get_cached_value('Company',  company,  "default_currency")

	if not conversion_rate:
		frappe.throw(_("{0} is mandatory. Maybe Currency Exchange record is not created for {1} to {2}.").format(
			conversion_rate_label, currency, company_currency))


def set_balance_in_account_currency(gl_dict, account_currency=None, conversion_rate=None, company_currency=None):
	if (not conversion_rate) and (account_currency != company_currency):
		frappe.throw(_("Account: {0} with currency: {1} can not be selected").format(gl_dict.account, account_currency))

	gl_dict["account_currency"] = company_currency if account_currency == company_currency else account_currency

	# set debit/credit in account currency if not provided
	if flt(gl_dict.debit) and not flt(gl_dict.debit_in_account_currency):
		gl_dict.debit_in_account_currency = gl_dict.debit if account_currency == company_currency \
			else flt(gl_dict.debit / conversion_rate, 2)

	if flt(gl_dict.credit) and not flt(gl_dict.credit_in_account_currency):
		gl_dict.credit_in_account_currency = gl_dict.credit if account_currency == company_currency \
			else flt(gl_dict.credit / conversion_rate, 2)


def get_supplier_block_status(party_name):
	"""
	Returns a dict containing the values of `on_hold`, `release_date` and `hold_type` of
	a `Supplier`
	"""
	supplier = frappe.get_doc('Supplier', party_name)
	info = {
		'on_hold': supplier.on_hold,
		'release_date': supplier.release_date,
		'hold_type': supplier.hold_type
	}
	return info


@erpnext.allow_regional
def validate_regional(doc):
	pass
