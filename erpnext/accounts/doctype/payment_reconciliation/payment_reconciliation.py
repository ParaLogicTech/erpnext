# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# For license information, please see license.txt

import frappe
import erpnext
from frappe import _, scrub
from frappe.utils import flt, getdate, cstr, now_datetime, cint, fmt_money
from frappe.model.document import Document
from erpnext.accounts.doctype.account.account import get_account_currency
from erpnext.accounts.utils import (
	get_advance_against_voucher_types, get_held_invoices,
)
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_all_dimension_fields


class PaymentReconciliation(Document):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.precision = frappe.get_precision("GL Entry", "debit") or 2

	def load_from_db(self):
		doc_dict = frappe.new_doc(self.doctype, as_dict=True)
		doc_dict["name"] = self.doctype
		super(Document, self).__init__(doc_dict)

	def save(self):
		return

	@staticmethod
	def get_list(args):
		pass

	@staticmethod
	def get_count(args):
		pass

	@staticmethod
	def get_stats(args):
		pass

	def db_insert(self, *args, **kwargs):
		pass

	def db_update(self, *args, **kwargs):
		pass

	def delete(self, *args, **kwargs):
		pass

	@frappe.whitelist()
	def get_unreconciled_entries(self):
		self.validate_mandatory_fields()

		unreconciled_payment_entries = self.get_unreconciled_payment_entries()
		self.set('payments', [])
		for d in unreconciled_payment_entries:
			self.append('payments', d)

		outstanding_invoices = self.get_outstanding_invoices()
		self.set('invoices', [])
		for d in outstanding_invoices:
			inv = self.append('invoices')
			inv.invoice_type = d.get('voucher_type')
			inv.invoice_number = d.get('voucher_no')
			inv.invoice_date = d.get('posting_date')
			inv.amount = flt(d.get('invoice_amount'))
			inv.outstanding_amount = d.get('outstanding_amount')
			inv.currency = d.get('currency')
			inv.exchange_rate = d.get('exchange_rate')

	@frappe.whitelist()
	def allocate_entries(self, args):
		self.validate_entries_for_allocation()

		entries = self.get_allocated_entries(args)
		self.set("allocation", [])
		for entry in entries:
			if entry.allocated_amount:
				self.append("allocation", entry)

	@frappe.whitelist()
	def reconcile(self):
		self.validate_mandatory_fields()
		self.validate_allocation()
		self.reconcile_allocations()
		frappe.msgprint(_("Payments Reconciled Successfully"))

		self.get_unreconciled_entries()

	def validate_mandatory_fields(self):
		for fieldname in ["company", "party_type", "party", "receivable_payable_account"]:
			if not self.get(fieldname):
				frappe.throw(_("Please select {0} first").format(self.meta.get_label(fieldname)))

	def validate_entries_for_allocation(self):
		if not self.get("invoices"):
			frappe.throw(_("No records found in the Invoices table"))

		if not self.get("payments"):
			frappe.throw(_("No records found in the Payments table"))

	def validate_allocation(self):
		invoices_map = {}
		payments_map = {}
		invoice_allocated_amounts = {}
		payment_allocated_amounts = {}

		for inv in self.get("invoices"):
			invoices_map.setdefault((inv.invoice_type, inv.invoice_number), flt(inv.outstanding_amount, self.precision))
		for pay in self.get("payments"):
			amount = flt(pay.get("amount"), self.precision)
			payments_map.setdefault((pay.reference_type, pay.reference_name, cstr(pay.reference_row)), frappe._dict({
				"unreconciled_amount": amount,
				"amount": amount,
			}))

		for row in self.get("allocation"):
			row.allocated_amount = flt(row.allocated_amount, self.precision)
			if not flt(row.allocated_amount):
				continue

			invoice_key = (row.invoice_type, row.invoice_number)
			payment_key = (row.reference_type, row.reference_name, cstr(row.reference_row))

			pay_obj = payments_map[payment_key]
			row.unreconciled_amount = flt(pay_obj.unreconciled_amount, self.precision)
			row.amount = flt(pay_obj.amount, self.precision)

			invoice_allocated_amounts.setdefault(invoice_key, 0)
			invoice_allocated_amounts[invoice_key] += flt(row.allocated_amount)
			invoice_total_outstanding = flt(invoices_map[invoice_key], self.precision)
			invoice_total_allocated = flt(invoice_allocated_amounts[invoice_key], self.precision)

			payment_allocated_amounts.setdefault(payment_key, 0)
			payment_allocated_amounts[payment_key] += flt(row.allocated_amount)

			payment_total_unreconciled = pay_obj.unreconciled_amount
			payment_total_allocated = flt(payment_allocated_amounts[payment_key], self.precision)

			df = row.meta.get_field("allocated_amount")

			if invoice_total_allocated > invoice_total_outstanding:
				frappe.throw(_("Row {0}: Total Allocated Amount {1} cannot be greater than the Outstanding Amount {2} of {3} {4}").format(
					row.idx,
					frappe.bold(frappe.format(invoice_total_allocated, df=df, doc=row)),
					frappe.bold(frappe.format(invoice_total_outstanding, df=df, doc=row)),
					row.invoice_type,
					row.invoice_number
				))

			if payment_total_allocated > payment_total_unreconciled:
				frappe.throw(_("Row {0}: Total Allocated Amount {1} cannot be greater than the Total Unreconciled Payment Amount {2} of {3} {4}").format(
					row.idx,
					frappe.bold(frappe.format(payment_total_allocated, df=df, doc=row)),
					frappe.bold(frappe.format(payment_total_unreconciled, df=df, doc=row)),
					row.reference_type,
					row.reference_name,
				))

			if row.allocated_amount > row.amount:
				frappe.throw(_("Row {0}: Allocated Amount {1} cannot be greater than the Remaining Unreconciled Payment Amount {2} of {3} {4}").format(
					row.idx,
					frappe.bold(row.get_formatted("allocated_amount")),
					frappe.bold(row.get_formatted("amount")),
					row.reference_type,
					row.reference_name,
				))

			pay_obj.amount = flt(pay_obj.amount - row.allocated_amount, self.precision)

		if not invoice_allocated_amounts or not payment_allocated_amounts:
			frappe.throw(_("No records found in the Allocation table"))

	def get_unreconciled_payment_entries(self):
		order_doctypes = get_advance_against_voucher_types()

		filters = {
			"against_account": self.get("bank_cash_account"),
			"from_payment_date": self.get("from_payment_date"),
			"to_payment_date": self.get("to_payment_date"),
			"min_payment_amount": self.get("min_payment_amount"),
			"max_payment_amount": self.get("max_payment_amount"),
		}

		payment_entries = get_unreconciled_payment_entries(
			self.party_type,
			self.party,
			self.receivable_payable_account,
			order_doctype=order_doctypes,
			against_all_orders=True,
			limit=self.payment_limit,
			filters=filters,
		)

		journal_entries = get_unreconciled_journal_entries(
			self.party_type,
			self.party,
			self.receivable_payable_account,
			order_doctype=order_doctypes,
			against_all_orders=True,
			limit=self.payment_limit,
			filters=filters,
		)

		dr_cr_notes = get_unreconciled_dr_cr_notes(
			self.party_type,
			self.party,
			self.receivable_payable_account,
			limit=self.payment_limit,
			filters=filters,
		)

		all_entries = payment_entries + journal_entries + dr_cr_notes
		all_entries = sorted(all_entries, key=lambda k: k.get("posting_date") or getdate())
		if self.payment_limit:
			all_entries = all_entries[:self.payment_limit]

		return all_entries

	def get_outstanding_invoices(self):
		filters = {
			"from_invoice_date": self.get("from_invoice_date"),
			"to_invoice_date": self.get("to_invoice_date"),
			"from_due_date": self.get("from_due_date"),
			"to_due_date": self.get("to_due_date"),
			"min_outstanding_amount": self.get("min_outstanding_amount"),
			"max_outstanding_amount": self.get("max_outstanding_amount"),
		}
		dimension_fields = get_all_dimension_fields()
		for f in dimension_fields:
			if self.get(f):
				filters[f] = self.get(f)

		outstanding_invoices = get_outstanding_invoices(
			self.party_type,
			self.party,
			self.receivable_payable_account,
			filters=filters,
		)

		if self.invoice_limit:
			outstanding_invoices = outstanding_invoices[:self.invoice_limit]

		return outstanding_invoices

	def get_allocated_entries(self, args):
		entries = []
		for pay in args.get("payments"):
			pay.update({"unreconciled_amount": flt(pay.get("amount"), self.precision)})
			for inv in args.get("invoices"):
				if flt(pay.get("amount"), self.precision) >= flt(inv.get("outstanding_amount"), self.precision):
					alloc = self.get_allocated_entry(pay, inv, allocated_amount=inv["outstanding_amount"])
					pay["amount"] = flt(pay.get("amount")) - flt(inv.get("outstanding_amount"))
					pay["amount"] = flt(pay.get("amount"), self.precision)
					inv["outstanding_amount"] = 0
				else:
					alloc = self.get_allocated_entry(pay, inv, allocated_amount=pay["amount"])
					inv["outstanding_amount"] = flt(inv.get("outstanding_amount")) - flt(pay.get("amount"))
					inv["outstanding_amount"] = flt(inv.get("outstanding_amount"), self.precision)
					pay["amount"] = 0

				alloc.difference_amount = calculate_difference_amount(
					alloc,
					account=self.receivable_payable_account,
					party_type=self.party_type,
				)
				alloc.difference_account = get_default_exchange_gain_loss_account(self.company)

				if pay.get("amount") <= 0:
					entries.append(alloc)
					break
				elif inv.get("outstanding_amount") <= 0:
					entries.append(alloc)
					continue

			else:
				break

		return entries

	def get_allocated_entry(self, pay, inv, allocated_amount):
		return frappe._dict({
			"reference_type": pay.get("reference_type"),
			"reference_name": pay.get("reference_name"),
			"reference_row": pay.get("reference_row"),
			"invoice_type": inv.get("invoice_type"),
			"invoice_number": inv.get("invoice_number"),
			"unreconciled_amount": pay.get("unreconciled_amount"),
			"amount": pay.get("amount"),
			"allocated_amount": flt(allocated_amount, self.precision),
			"difference_amount": pay.get("difference_amount"),
			"currency": inv.get("currency"),
			"exchange_rate": flt(inv.get("exchange_rate")) or 1,
			"payment_exchange_rate": flt(pay.get("exchange_rate")) or 1,
			"reconciliation_posting_date": min(getdate(pay.get("posting_date")), getdate(inv.get("posting_date")))
		})

	def reconcile_allocations(self):
		reconciliation_list = []
		for row in self.get("allocation"):
			if row.invoice_number and flt(row.allocated_amount) > 0:
				reconciliation_args = self.get_reconciliation_args(row)
				reconciliation_list.append(reconciliation_args)

		if reconciliation_list:
			reconcile_payments_against_invoices(reconciliation_list)

	def get_reconciliation_args(self, row):
		return frappe._dict({
			"voucher_type": row.get("reference_type"),
			"voucher_no": row.get("reference_name"),
			"voucher_detail_no": row.get("reference_row"),
			"against_voucher_type": row.get("invoice_type"),
			"against_voucher": row.get("invoice_number"),
			"account": self.receivable_payable_account,
			"party_type": self.party_type,
			"party": self.party,
			"unreconciled_amount": flt(row.get("unreconciled_amount")),
			"remaining_unreconciled_amount": flt(row.get("amount")),
			"allocated_amount": flt(row.get("allocated_amount")),
			"currency": row.get("currency"),
			"exchange_rate": flt(row.get("exchange_rate")) or 1,
			"payment_exchange_rate": flt(row.get("payment_exchange_rate")) or 1,
			"difference_amount": flt(row.get("difference_amount")),
			"difference_account": row.get("difference_account"),
			"reconciliation_posting_date": row.get("reconciliation_posting_date"),
		})


@frappe.whitelist()
def calculate_difference_amount(args, account=None, party_type=None):
	args = frappe.parse_json(args)

	precision = frappe.get_precision("GL Entry", "debit") or 2

	invoice_exchange_rate = flt(args.get("exchange_rate"))
	payment_exchange_rate = flt(args.get("payment_exchange_rate"))
	allocated_amount = flt(args.get("allocated_amount"), precision)
	if not invoice_exchange_rate or not payment_exchange_rate or not allocated_amount:
		return 0

	account = account or args.get("account")
	party_type = party_type or args.get("party_type")
	if not account or not party_type:
		return 0

	company = frappe.get_cached_value("Account", account, "company")
	company_currency = erpnext.get_company_currency(company)
	account_currency = get_account_currency(account)
	if not account_currency or not company_currency:
		return 0

	party_account_type = erpnext.get_party_account_type(party_type)

	difference_amount = 0
	if account_currency != company_currency and payment_exchange_rate != invoice_exchange_rate:
		base_payment_amount = flt(allocated_amount * payment_exchange_rate, precision)
		base_invoice_amount = flt(allocated_amount * invoice_exchange_rate, precision)
		difference_amount = flt(base_invoice_amount - base_payment_amount, precision)
		if party_account_type == "Payable":
			difference_amount = -difference_amount

	return difference_amount


def get_outstanding_invoices(
	party_type,
	party,
	account,
	include_negative_outstanding=False,
	include_negative_payments=False,
	filters=None,
	additional_conditions=None,
):
	from erpnext.accounts.doctype.journal_entry.journal_entry import get_average_party_exchange_rate_on_journal_entry

	outstanding_invoices = []
	if not party_type or not party or not account:
		return []

	# prepare queries
	account_doc = frappe.get_cached_doc("Account", account)
	company = account_doc.company
	company_currency = erpnext.get_company_currency(company)
	account_currency = get_account_currency(account)
	dimension_fields = get_all_dimension_fields()

	if account_doc.account_type in ("Receivable", "Payable"):
		party_account_type = account_doc.account_type
	else:
		party_account_type = erpnext.get_party_account_type(party_type)

	if party_account_type == "Receivable":
		dr_or_cr = "debit_in_account_currency - credit_in_account_currency"
		payment_dr_or_cr = "credit_in_account_currency - debit_in_account_currency"
	else:
		dr_or_cr = "credit_in_account_currency - debit_in_account_currency"
		payment_dr_or_cr = "debit_in_account_currency - credit_in_account_currency"

	# prepare conditions
	filters = frappe._dict(filters or {})
	filters.update({
		"party_type": party_type,
		"party": party,
		"account": account
	})

	filter_conditions = []
	having_conditions = []

	if include_negative_payments:
		having_conditions.append("(voucher_type != 'Payment Entry' or invoice_amount < 0)")
	else:
		filter_conditions.append("voucher_type != 'Payment Entry'")

	if filters.get("company"):
		filter_conditions.append("company = %(company)s")

	if filters.get("voucher_type"):
		filter_conditions.append("voucher_type = %(voucher_type)s")
	if filters.get("voucher_no"):
		filter_conditions.append("voucher_no = %(voucher_no)s")

	if filters.get("from_posting_date"):
		filter_conditions.append("posting_date >= %(from_posting_date)s")
	if filters.get("to_posting_date"):
		filter_conditions.append("posting_date <= %(to_posting_date)s")

	if filters.get("from_due_date"):
		filter_conditions.append("due_date >= %(from_due_date)s")
	if filters.get("to_due_date"):
		filter_conditions.append("due_date <= %(to_due_date)s")

	if filters.get("min_invoice_amount"):
		having_conditions.append("invoice_amount >= %(min_invoice_amount)s")
	if filters.get("max_invoice_amount"):
		having_conditions.append("invoice_amount <= %(max_invoice_amount)s")

	dimension_filters = {f: filters.get(f) for f in dimension_fields if filters.get(f)}
	if dimension_filters:
		dimension_conditions_str = " and ".join([f"dim.`{f}` = %({f})s" for f in dimension_filters.keys()])
		filter_conditions.append(f"""exists(select dim.name from `tabGL Entry` dim
			where dim.voucher_type = `tabGL Entry`.voucher_type and dim.voucher_no = `tabGL Entry`.voucher_no
				and dim.party_type = %(party_type)s and dim.party = %(party)s and dim.account = %(account)s
				and {dimension_conditions_str}
		)""")

	filter_conditions_str = "and " + " and ".join(filter_conditions) if filter_conditions else ""
	having_conditions_str = "having " + " and ".join(having_conditions) if having_conditions else ""

	dimension_fields_str = ", ".join([f"`{f}`" for f in dimension_fields])
	dimension_fields_str = ", " + dimension_fields_str if dimension_fields_str else ""

	# load invoice data
	invoice_data = frappe.db.sql(f"""
		select
			voucher_no,
			voucher_type,
			posting_date,
			due_date,
			ifnull(sum({dr_or_cr}), 0) as invoice_amount,
			remarks
			{dimension_fields_str}
		from `tabGL Entry`
		where
			party_type = %(party_type)s
			and party = %(party)s
			and account = %(account)s
			and (against_voucher = '' or against_voucher is null)
			{filter_conditions_str}
			{additional_conditions or ""}
		group by voucher_type, voucher_no
		{having_conditions_str}
		order by posting_date, creation
	""", filters, as_dict=True)

	# load allocated payments
	payment_entries = frappe.db.sql(f"""
		select
			against_voucher_type,
			against_voucher,
			ifnull(sum({payment_dr_or_cr}), 0) as payment_amount
		from
			`tabGL Entry`
		where
			party_type = %(party_type)s
			and party = %(party)s
			and account = %(account)s
			and against_voucher is not null and against_voucher != ''
		group by against_voucher_type, against_voucher
	""", {
		"party_type": party_type,
		"party": party,
		"account": account
	}, as_dict=True)

	payment_against_map = frappe._dict()
	for pay in payment_entries:
		payment_against_map.setdefault((pay.against_voucher_type, pay.against_voucher), pay.payment_amount)

	# load held invoices
	held_invoices = get_held_invoices(party_type, party)

	# build outstanding list
	precision = frappe.get_precision("GL Entry", "debit") or 2
	for inv in invoice_data:
		if inv.voucher_type == "Purchase Invoice" and inv.voucher_no in held_invoices:
			continue

		payment_amount = flt(payment_against_map.get((inv.voucher_type, inv.voucher_no)))
		outstanding_amount = flt(inv.invoice_amount - payment_amount, precision)
		diff = abs(outstanding_amount) if include_negative_outstanding else outstanding_amount

		if diff > 0.5 / (10 ** precision):
			inv["invoice_amount"] = flt(inv.invoice_amount)
			inv["payment_amount"] = payment_amount
			inv["outstanding_amount"] = outstanding_amount
			outstanding_invoices.append(inv)

	# post filter
	if flt(filters.get("min_outstanding_amount")):
		outstanding_invoices = [d for d in outstanding_invoices if d["outstanding_amount"] >= flt(filters.get("min_outstanding_amount"))]
	if flt(filters.get("max_outstanding_amount")):
		outstanding_invoices = [d for d in outstanding_invoices if d["outstanding_amount"] <= flt(filters.get("max_outstanding_amount"))]

	# get voucher details
	for inv in outstanding_invoices:
		voucher_meta = frappe.get_meta(inv.voucher_type)

		inv["currency"] = account_currency
		inv["exchange_rate"] = 1

		if account_currency != company_currency:
			if inv.voucher_type == "Journal Entry":
				inv["exchange_rate"] = get_average_party_exchange_rate_on_journal_entry(
					inv.voucher_no,
					party_type,
					party,
					account,
				)
			elif voucher_meta.has_field("conversion_rate"):
				inv["exchange_rate"] = flt(frappe.db.get_value(inv.voucher_type, inv.voucher_no, "conversion_rate")) or 1

		if inv.voucher_type == "Payment Entry":
			pe_details = frappe.db.get_value("Payment Entry", inv.voucher_no, [
				"payment_type",
				"source_exchange_rate", "target_exchange_rate",
				"paid_amount_after_tax", "received_amount_after_tax",
			], as_dict=1)

			inv["invoice_amount"] = -pe_details.paid_amount_after_tax if pe_details.payment_type == "Receive" else -pe_details.received_amount_after_tax
			inv["exchange_rate"] = pe_details.source_exchange_rate if pe_details.payment_type == "Receive" else pe_details.target_exchange_rate

		if voucher_meta.has_field("bill_no"):
			inv["bill_no"] = frappe.db.get_value(inv.voucher_type, inv.voucher_no, "bill_no", cache=True)

	outstanding_invoices = sorted(
		outstanding_invoices,
		key=lambda k: (k["outstanding_amount"] > 0, k["due_date"] or getdate())
	)
	return outstanding_invoices


def get_unreconciled_journal_entries(
	party_type,
	party,
	party_account,
	order_doctype=None,
	order_list=None,
	include_unallocated=True,
	against_all_orders=False,
	against_project=None,
	limit=None,
	filters=None,
):
	journal_entries = []

	# prepare
	if erpnext.get_party_account_type(party_type) == "Receivable":
		dr_or_cr = "jea.credit_in_account_currency - jea.debit_in_account_currency"
		base_dr_or_cr = "jea.credit - jea.debit"
		payment_dr_or_cr = "gle_payment.debit_in_account_currency - gle_payment.credit_in_account_currency"
	else:
		dr_or_cr = "jea.debit_in_account_currency - jea.credit_in_account_currency"
		base_dr_or_cr = "jea.debit - jea.credit"
		payment_dr_or_cr = "gle_payment.credit_in_account_currency - gle_payment.debit_in_account_currency"

	if order_doctype and isinstance(order_doctype, str):
		order_doctype = [order_doctype]

	# filter conditions
	filters = frappe._dict(filters or {})
	filters.update({
		"party_type": party_type,
		"party": party,
		"account": party_account,
		"order_doctype": order_doctype,
		"order_list": order_list,
		"against_project": against_project,
		"limit": limit,
	})

	limit_cond = "limit %(limit)s" if limit else ""

	filter_conditions = []
	having_conditions = []

	if filters.get("against_account"):
		filter_conditions.append("""exists(select against.name from `tabJournal Entry Account` against
			where against.parent = je.name and against.account = %(against_account)s)""")

	if filters.get("from_payment_date"):
		filter_conditions.append("je.posting_date >= %(from_payment_date)s")
	if filters.get("to_payment_date"):
		filter_conditions.append("je.posting_date <= %(to_payment_date)s")

	if filters.get("min_payment_amount"):
		having_conditions.append("amount >= %(min_payment_amount)s")
	if filters.get("max_payment_amount"):
		having_conditions.append("amount <= %(max_payment_amount)s")

	filter_conditions_str = "and " + " and ".join(filter_conditions) if filter_conditions else ""

	# JVs against order documents
	if order_list or (against_all_orders and order_doctype):
		if order_list:
			order_condition = "and (jea.reference_type, jea.reference_name) in %(order_list)s"
		else:
			order_condition = "and jea.reference_type in %(order_doctype)s and jea.reference_name is not null and jea.reference_name != ''"

		against_project_condition = ""
		if against_project:
			against_project_condition = """and (
				jea.project = %(against_project)s or (je.project = %(against_project)s and ifnull(jea.project, '') = '')
			)"""

		having_conditions_str = "having " + " and ".join(having_conditions) if having_conditions else ""

		journal_entries += frappe.db.sql(f"""
			select
				'Journal Entry' as reference_type,
				je.name as reference_name,
				je.remark as remarks,
				{dr_or_cr} as amount,
				jea.name as reference_row,
				jea.reference_name as against_order,
				jea.reference_type as against_order_doctype,
				je.posting_date,
				if(ifnull(jea.project, '') != '', jea.project, je.project) as project,
				jea.account_currency as currency,
				jea.exchange_rate
			from `tabJournal Entry Account` jea
			inner join `tabJournal Entry` je on je.name = jea.parent
			where je.docstatus = 1
				and jea.account = %(account)s
				and jea.party_type = %(party_type)s
				and jea.party = %(party)s
				and {dr_or_cr} > 0
				{order_condition}
				{against_project_condition if not order_list else ""}
				{filter_conditions_str}
			{having_conditions_str}
			order by je.posting_date, je.creation
			{limit_cond}
		""", filters, as_dict=1)

	# Unallocated payment JVs
	if include_unallocated:
		against_project_condition = ""
		if against_project:
			against_project_condition = """and (je.project = %(against_project)s or exists(
				select ch.name from `tabJournal Entry Account` ch
					where ch.parent = je.name and ch.project = %(against_project)s
						and ch.account = %(account)s and ch.party_type = %(party_type)s and ch.party = %(party)s
			))"""

		having_conditions_str = "and " + " and ".join(having_conditions) if having_conditions else ""

		journal_entries += frappe.db.sql(f"""
			select
				'Journal Entry' as reference_type,
				je.name as reference_name,
				je.remark as remarks,
				je.posting_date,
				if(ifnull(jea.project, '') != '', jea.project, je.project) as project,
				jea.account_currency as currency,
				ifnull(({base_dr_or_cr}) / ({dr_or_cr}), avg(jea.exchange_rate)) as exchange_rate,
				ifnull(sum({dr_or_cr}), 0) - (
					select ifnull(sum({payment_dr_or_cr}), 0)
					from `tabGL Entry` gle_payment
					where
						gle_payment.against_voucher_type = 'Journal Entry'
						and gle_payment.against_voucher = je.name
						and gle_payment.party_type = %(party_type)s
						and gle_payment.party = %(party)s
						and gle_payment.account = %(account)s
						and abs({payment_dr_or_cr}) > 0
				) as amount
			from `tabJournal Entry Account` jea
			inner join `tabJournal Entry` je on je.name = jea.parent
			where je.docstatus = 1
				and jea.party_type = %(party_type)s
				and jea.party = %(party)s
				and jea.account = %(account)s
				and (jea.reference_name = '' or jea.reference_name is null)
				and abs({dr_or_cr}) > 0
				{against_project_condition}
				{filter_conditions_str}
			group by je.name
			having amount > 0.005 {having_conditions_str}
			order by je.posting_date, je.creation
			{limit_cond}
		""", filters, as_dict=True)

	return journal_entries


def get_unreconciled_payment_entries(
	party_type,
	party,
	party_account,
	order_doctype=None,
	order_list=None,
	include_unallocated=True,
	against_all_orders=False,
	against_project=None,
	limit=None,
	filters=None,
):
	# prepare
	party_account_type = erpnext.get_party_account_type(party_type)
	party_account_field = "paid_from" if party_account_type == "Receivable" else "paid_to"
	against_account_field = "paid_to" if party_account_type == "Receivable" else "paid_from"
	amount_before_tax_field = "paid_amount_before_tax" if party_account_type == "Receivable" else "received_amount_before_tax"
	exchange_rate_field = "source_exchange_rate" if party_account_type == "Receivable" else "target_exchange_rate"
	payment_type = "Receive" if party_account_type == "Receivable" else "Pay"

	if order_doctype and isinstance(order_doctype, str):
		order_doctype = [order_doctype]

	# filter conditions
	filters = frappe._dict(filters or {})
	filters.update({
		"account": party_account,
		"party_type": party_type,
		"party": party,
		"payment_type": payment_type,
		"order_doctype": order_doctype,
		"order_list": order_list,
		"against_project": against_project,
		"limit": limit,
	})

	limit_cond = "limit %(limit)s" if limit else ""

	against_project_condition = ""
	if against_project:
		against_project_condition = "and pe.project = %(against_project)s"

	filter_conditions = []
	having_conditions = []

	if filters.get("against_account"):
		filter_conditions.append(f"pe.{against_account_field} = %(against_account)s")

	if filters.get("from_payment_date"):
		filter_conditions.append("pe.posting_date >= %(from_payment_date)s")
	if filters.get("to_payment_date"):
		filter_conditions.append("pe.posting_date <= %(to_payment_date)s")

	if filters.get("min_payment_amount"):
		having_conditions.append("amount >= %(min_payment_amount)s")
	if filters.get("max_payment_amount"):
		having_conditions.append("amount <= %(max_payment_amount)s")

	filter_conditions_str = "and " + " and ".join(filter_conditions) if filter_conditions else ""
	having_conditions_str = "having " + " and ".join(having_conditions) if having_conditions else ""

	# Payment Entries against orders
	payment_entries_against_order = []
	if order_list or (against_all_orders and order_doctype):
		if order_list:
			order_condition = "and (pref.reference_doctype, pref.reference_name) in %(order_list)s"
		else:
			order_condition = "and pref.reference_doctype in %(order_doctype)s"

		payment_entries_against_order = frappe.db.sql(f"""
			select
				'Payment Entry' as reference_type,
				pe.name as reference_name,
				pe.remarks,
				pref.allocated_amount as amount,
				pe.total_taxes_and_charges,
				pe.{amount_before_tax_field} as total_paid_amount,
				pref.name as reference_row,
				pref.reference_name as against_order,
				pref.reference_doctype as against_order_doctype,
				pe.posting_date,
				pe.project,
				pe.{party_account_field}_account_currency as currency,
				pe.{exchange_rate_field} as exchange_rate
			from `tabPayment Entry Reference` pref
			inner join `tabPayment Entry` pe on pe.name = pref.parent
			where pe.docstatus = 1
				and pe.{party_account_field} = %(account)s
				and pe.payment_type = %(payment_type)s
				and pe.party_type = %(party_type)s
				and pe.party = %(party)s
				{order_condition}
				{against_project_condition if not order_list else ""}
				{filter_conditions_str}
			{having_conditions_str}
			order by pe.posting_date, pe.creation
			{limit_cond}
		""", filters, as_dict=1)

	# Unallocated Payments
	unallocated_payment_entries = []
	if include_unallocated:
		unallocated_payment_entries = frappe.db.sql(f"""
			select
				'Payment Entry' as reference_type,
				pe.name as reference_name,
				pe.remarks,
				pe.unallocated_amount as amount,
				pe.total_taxes_and_charges,
				pe.{amount_before_tax_field} as total_paid_amount,
				pe.project,
				pe.posting_date,
				pe.{party_account_field}_account_currency as currency,
				pe.{exchange_rate_field} as exchange_rate
			from `tabPayment Entry` pe
			where pe.docstatus = 1
				and pe.{party_account_field} = %(account)s
				and pe.party_type = %(party_type)s
				and pe.party = %(party)s
				and pe.payment_type = %(payment_type)s
				and pe.unallocated_amount > 0
				{against_project_condition}
				{filter_conditions_str}
			{having_conditions_str}
			order by pe.posting_date, pe.creation
			{limit_cond}
		""", filters, as_dict=1)

	# merge and add advance tax
	out = payment_entries_against_order + unallocated_payment_entries
	for d in out:
		d.advance_tax = d.total_taxes_and_charges * d.amount / d.total_paid_amount if d.total_paid_amount else 0

	return out


def get_unreconciled_dr_cr_notes(
	party_type,
	party,
	party_account,
	order_list=None,
	include_unallocated=True,
	against_project=None,
	limit=None,
	filters=None,
):
	if party_type not in ("Customer", "Supplier"):
		return []

	invoice_doctype = "Sales Invoice" if party_type == "Customer" else "Purchase Invoice"
	item_doctype = "Sales Invoice Item" if party_type == "Customer" else "Purchase Invoice Item"
	item_meta = frappe.get_meta(item_doctype)
	party_field = "bill_to" if party_type == "Customer" else "supplier"

	# Filter Conditions
	filters = frappe._dict(filters or {})
	filters.update({
		"voucher_type": invoice_doctype,
		"party_type": party_type,
		"party": party,
		"account": party_account,
		"against_project": against_project,
		"limit": limit,
	})

	limit_cond = "limit %(limit)s" if limit else ""

	filter_conditions = []

	if filters.get("against_account"):
		return []

	if filters.get("from_payment_date"):
		filter_conditions.append("inv.posting_date >= %(from_payment_date)s")
	if filters.get("to_payment_date"):
		filter_conditions.append("inv.posting_date <= %(to_payment_date)s")

	if filters.get("min_payment_amount"):
		filter_conditions.append("-inv.outstanding_amount >= %(min_payment_amount)s")
	if filters.get("max_payment_amount"):
		filter_conditions.append("-inv.outstanding_amount <= %(max_payment_amount)s")

	# Against Order and Against Project
	order_list = order_list or []
	valid_order_map = {}
	for order_doctype, order_name in order_list:
		order_field = scrub(order_doctype)
		if item_meta.has_field(order_field):
			valid_order_map.setdefault(order_field, []).append(order_name)

	against_order_condition = ""
	if valid_order_map:
		order_conditions = []
		for order_field, order_names in valid_order_map.items():
			order_conditions.append("ch.`{0}` in ({1})".format(
				order_field,
				", ".join(frappe.db.escape(name) for name in order_names)
			))
		against_order_condition = f"""exists(select ch.name from `tab{item_doctype}` ch
			where ch.parent = inv.name and ({' or '.join(order_conditions)})
		)"""

	against_project_condition = ""
	if against_project:
		against_project_condition = "inv.project = %(against_project)s"

	if order_list and not valid_order_map and not include_unallocated:
		return []

	if include_unallocated:
		if against_project_condition and against_order_condition:
			filter_conditions.append(f"({against_project_condition} or {against_order_condition})")
		elif against_project_condition:
			filter_conditions.append(against_project_condition)
	else:
		if against_order_condition:
			filter_conditions.append(against_order_condition)
		elif against_project_condition:
			filter_conditions.append(against_project_condition)

	filter_conditions_str = "and " + " and ".join(filter_conditions) if filter_conditions else ""

	unreconciled_dr_cr_notes = frappe.db.sql(f"""
		select
			'{invoice_doctype}' as reference_type,
			inv.name as reference_name,
			inv.remarks,
			-inv.outstanding_amount as amount,
			inv.project,
			inv.posting_date,
			inv.party_account_currency as currency,
			inv.conversion_rate as exchange_rate
		from `tab{invoice_doctype}` inv
		where inv.docstatus = 1
			and inv.{party_field} = %(party)s
			and inv.outstanding_amount < 0
			and exists(
				select gl.name
				from `tabGL Entry` gl
				where gl.voucher_no = inv.name
					and gl.voucher_type = %(voucher_type)s
					and gl.party_type = %(party_type)s
					and gl.party = %(party)s
					and gl.account = %(account)s
			)
			{filter_conditions_str}
		order by inv.posting_date, inv.creation
		{limit_cond}
	""", filters, as_dict=True)

	return unreconciled_dr_cr_notes


def reconcile_payments_against_invoices(reconciliation_list):
	reconciled_payment_docs = {}
	reconcilation_jv_names = []

	for args in reconciliation_list:
		validate_reconciliation_args(args)
		check_if_unreconciled_entry_modified(args)

		payment_voucher_key = (args.voucher_type, args.voucher_no)
		if reconciled_payment_docs.get(payment_voucher_key):
			doc = reconciled_payment_docs.get(payment_voucher_key)
		else:
			doc = frappe.get_doc(args.voucher_type, args.voucher_no, for_update=True)
			doc.flags.ignore_validate_update_after_submit = True
			doc.flags.ignore_mandatory = True
			doc.flags.ignore_permissions = True
			reconciled_payment_docs[payment_voucher_key] = doc

		if flt(args.difference_amount) and args.voucher_type in ("Payment Entry", "Journal Entry"):
			jv_name = create_payment_reconciliation_journal_entry(args, doc, allocate_payment=False)
			args.payment_reconciliation_journal_entry = jv_name
			reconcilation_jv_names.append(jv_name)

		if args.voucher_type == "Journal Entry":
			reconcile_reference_in_journal_entry(args, doc)
		elif args.voucher_type == "Payment Entry":
			reconcile_reference_in_payment_entry(args, doc)
		else:
			jv_name = create_payment_reconciliation_journal_entry(args, doc, allocate_payment=True)
			reconcilation_jv_names.append(jv_name)

	for (voucher_type, voucher_no), doc in reconciled_payment_docs.items():
		if voucher_type in ("Payment Entry", "Journal Entry"):
			repost_reconciled_payment_voucher(doc)

	if reconcilation_jv_names:
		reconciliation_jv_links = [frappe.utils.get_link_to_form("Journal Entry", jv_name, target="_blank") for jv_name in reconcilation_jv_names]
		frappe.msgprint(_("Payment Reconciliation Journal Entry created: {0}").format(", ".join(reconciliation_jv_links)))


def repost_reconciled_payment_voucher(doc):
	doc.save()
	doc.make_gl_entries(cancel=1, adv_adj=1)
	doc.make_gl_entries(cancel=0, adv_adj=1)
	doc.update_expense_claim()


def validate_reconciliation_args(args):
	precision = frappe.get_precision("GL Entry", "debit")

	if "remaining_unreconciled_amount" not in args:
		args["remaining_unreconciled_amount"] = flt(args.get("unreconciled_amount"))

	if not args.get("party_type") or not args.get("party"):
		frappe.throw(_("Party not provided in payment reconcilation arguments"))
	if not args.get("account"):
		frappe.throw(_("Party Account not provided in payment reconcilation arguments"))
	if not args.get("voucher_type") or not args.get("voucher_no"):
		frappe.throw(_("Payment Voucher not provided in payment reconcilation arguments"))
	if not args.get("against_voucher_type") or not args.get("against_voucher"):
		frappe.throw(_("Invoice Voucher not provided in payment reconcilation arguments"))

	args["party_account_type"] = erpnext.get_party_account_type(args.party_type)
	if args.get("party_account_type") == "Receivable":
		args["dr_or_cr"] = "credit_in_account_currency"
		args["reverse_dr_or_cr"] = "debit_in_account_currency"
	else:
		args["dr_or_cr"] = "debit_in_account_currency"
		args["reverse_dr_or_cr"] = "credit_in_account_currency"

	args["company"] = frappe.get_cached_value("Account", args.account, "company")
	args["company_currency"] = erpnext.get_company_currency(args.company)
	args["currency"] = get_account_currency(args.get("account"))

	if flt(args.get("difference_amount")) and not args.get("difference_account"):
		args["difference_account"] = get_default_exchange_gain_loss_account(args.get("company"))

	if not flt(args.get("exchange_rate")):
		args["exchange_rate"] = 1

	if flt(args.get("allocated_amount"), precision) < 0:
		frappe.throw(_("Allocated Amount {0} cannot be negative for {1} {2}").format(
			frappe.bold(fmt_money(args.get("allocated_amount"), currency=args.get("currency"))),
			args.get("voucher_type"),
			args.get("voucher_no"),
		))

	elif flt(args.get("allocated_amount"), precision) == 0:
		frappe.throw(_("Allocated Amount {0} cannot be zero for {1} {2}").format(
			frappe.bold(fmt_money(args.get("allocated_amount"), currency=args.get("currency"))),
			args.get("voucher_type"),
			args.get("voucher_no"),
		))

	elif flt(args.get("allocated_amount"), precision) > flt(args.get("unreconciled_amount"), precision):
		frappe.throw(_("Allocated Amount {0} cannot be greater than the Total Unreconciled Payment Amount {1} of {2} {3}").format(
			frappe.bold(fmt_money(args.get("allocated_amount"), currency=args.get("currency"))),
			frappe.bold(fmt_money(args.get("unreconciled_amount"), currency=args.get("currency"))),
			args.get("voucher_type"),
			args.get("voucher_no"),
		))

	elif flt(args.get("allocated_amount"), precision) > flt(args.get("remaining_unreconciled_amount"), precision):
		frappe.throw(_("Allocated Amount {0} cannot be greater than the Remaining Unreconciled Payment Amount {1} of {2} {3}").format(
			frappe.bold(fmt_money(args.get("allocated_amount"), currency=args.get("currency"))),
			frappe.bold(fmt_money(args.get("remaining_unreconciled_amount"), currency=args.get("currency"))),
			args.get("voucher_type"),
			args.get("voucher_no"),
		))


def get_default_exchange_gain_loss_account(company):
	return frappe.get_cached_value(
		"Company", company, "exchange_gain_loss_account"
	)


def check_if_unreconciled_entry_modified(args):
	"""
		check if there is already a voucher reference
		check if amount is same
		check if jv is submitted
	"""

	match = None
	args = args.copy()

	if args.voucher_type == "Journal Entry":
		if args.voucher_detail_no:
			args["advance_against_voucher_types"] = [""] + get_advance_against_voucher_types()
			match = frappe.db.sql(f"""
				select je.name
				from `tabJournal Entry Account` jea
				inner join `tabJournal Entry` je on je.name = jea.parent
				where je.docstatus = 1
					and jea.account = %(account)s
					and je.name = %(voucher_no)s
					and jea.name = %(voucher_detail_no)s
					and jea.party_type = %(party_type)s
					and jea.party = %(party)s
					and ifnull(jea.reference_type, '') in %(advance_against_voucher_types)s
					and jea.{args.dr_or_cr} - jea.{args.reverse_dr_or_cr} = %(unreconciled_amount)s
				for update
			""", args)
		else:
			dr_or_cr = f"gle.{args.dr_or_cr} - gle.{args.reverse_dr_or_cr}"
			match = frappe.db.sql(f"""
				select sum({dr_or_cr}) as outstanding_amount
				from `tabGL Entry` gle
				left join `tabJournal Entry` je on je.name = gle.voucher_no and gle.voucher_type = 'Journal Entry'
				where (
					(
						gle.voucher_type = 'Journal Entry'
						and gle.voucher_no = %(voucher_no)s
						and (gle.against_voucher is null or gle.against_voucher = '')
					)
					or (
						gle.against_voucher_type = 'Journal Entry'
						and gle.against_voucher = %(voucher_no)s
					)
				)
					and gle.party_type = %(party_type)s
					and gle.party = %(party)s
					and gle.account = %(account)s
				having outstanding_amount = %(unreconciled_amount)s
				for update
			""", args)

	elif args.voucher_type == "Payment Entry":
		party_account_field = ("paid_from" if erpnext.get_party_account_type(args.party_type) == 'Receivable' else "paid_to")

		if args.voucher_detail_no:
			args["advance_against_voucher_types"] = get_advance_against_voucher_types()
			match = frappe.db.sql(f"""
				select pe.name
				from `tabPayment Entry Reference` pref
				inner join `tabPayment Entry` pe on pe.name = pref.parent
				where pe.docstatus = 1
					and pe.name = %(voucher_no)s
					and pref.name = %(voucher_detail_no)s
					and pe.party_type = %(party_type)s
					and pe.party = %(party)s
					and pe.{party_account_field} = %(account)s
					and pref.reference_doctype in %(advance_against_voucher_types)s
					and pref.allocated_amount = %(unreconciled_amount)s
				for update
			""", args)
		else:
			match = frappe.db.sql(f"""
				select name
				from `tabPayment Entry`
				where docstatus = 1
					and name = %(voucher_no)s
					and party_type = %(party_type)s
					and party = %(party)s
					and {party_account_field} = %(account)s
					and unallocated_amount = %(unreconciled_amount)s
				for update
			""", args)

	elif args.voucher_type in ("Sales Invoice", "Purchase Invoice"):
		dr_or_cr = f"gle.{args.dr_or_cr} - gle.{args.reverse_dr_or_cr}"
		match = frappe.db.sql(f"""
			select sum({dr_or_cr}) as outstanding_amount
			from `tabGL Entry` gle
			left join `tab{args.voucher_type}` inv on inv.name = gle.voucher_no and gle.voucher_type = %(voucher_type)s
			where (
				(
					gle.voucher_type = %(voucher_type)s
					and gle.voucher_no = %(voucher_no)s
					and (gle.against_voucher is null or gle.against_voucher = '')
				)
				or (
					gle.against_voucher_type = %(voucher_type)s
					and gle.against_voucher = %(voucher_no)s
				)
			)
				and gle.party_type = %(party_type)s
				and gle.party = %(party)s
				and gle.account = %(account)s
			having outstanding_amount = %(unreconciled_amount)s
			for update
		""", args)

	if not match:
		frappe.throw(_(
			"{0} {1} was modified during payment / advance reconcilation. Please load unreconciled entries / advances again"
		).format(
			args.voucher_type, args.voucher_no
		))


def reconcile_reference_in_journal_entry(args, jv_doc):
	"""
		Updates against document, if partial amount splits into rows
	"""

	dr_or_cr = args["dr_or_cr"]
	reverse_dr_or_cr = "credit_in_account_currency" if dr_or_cr == "debit_in_account_currency" else "debit_in_account_currency"
	base_dr_or_cr = "debit" if dr_or_cr == "debit_in_account_currency" else "credit"
	base_reverse_dr_or_cr = "credit" if dr_or_cr == "debit_in_account_currency" else "debit"

	against_voucher_type = args.against_voucher_type
	against_voucher = args.against_voucher
	if args.payment_reconciliation_journal_entry:
		against_voucher_type = "Journal Entry"
		against_voucher = args.payment_reconciliation_journal_entry

	rows_to_reconcile = []
	if args.get("voucher_detail_no"):
		rows_to_reconcile.append(jv_doc.get("accounts", {"name": args["voucher_detail_no"]})[0])
	else:
		for row in jv_doc.accounts:
			if (
				row.party_type == args['party_type']
				and row.party == args['party']
				and row.account == args['account']
				and not row.reference_type
				and not row.reference_name
			):
				rows_to_reconcile.append(row)

	amt_allocated = 0.0
	for jv_detail in rows_to_reconcile:
		jvd = frappe.copy_doc(jv_detail)

		diff = flt(jv_detail.get(dr_or_cr)) - flt(jv_detail.get(reverse_dr_or_cr))

		amt_allocatable = flt(
			min(diff, args["allocated_amount"] - amt_allocated),
			jv_detail.precision("debit")
		)
		original_dr_or_cr = diff
		original_reference_type = jv_detail.reference_type
		original_reference_name = jv_detail.reference_name

		jv_detail.set(dr_or_cr, amt_allocatable)
		jv_detail.set(base_dr_or_cr, amt_allocatable * flt(jv_detail.exchange_rate))
		jv_detail.set(reverse_dr_or_cr, 0)
		jv_detail.set(base_reverse_dr_or_cr, 0)

		jv_detail.set("reference_type", against_voucher_type)
		jv_detail.set("reference_name", against_voucher)

		if amt_allocatable < original_dr_or_cr:
			amount_in_account_currency = flt(flt(original_dr_or_cr) - flt(amt_allocatable), jv_detail.precision("debit"))
			amount_in_company_currency = amount_in_account_currency * flt(jvd.exchange_rate)

			# new entry with balance amount
			ch = jv_doc.append("accounts")

			# insert it in between
			new_idx = jv_detail.idx + 1
			for row in jv_doc.accounts:
				if row.idx >= new_idx:
					row.idx += 1
			ch.idx = new_idx

			ch.account = args['account']
			ch.account_type = jvd.account_type
			ch.account_currency = jvd.account_currency
			ch.exchange_rate = jvd.exchange_rate
			ch.party_type = args["party_type"]
			ch.party = args["party"]
			ch.party_name = jvd.party_name
			ch.cost_center = cstr(jvd.cost_center)
			ch.project = jvd.project
			ch.balance = flt(jvd.balance)
			ch.cheque_no = jvd.cheque_no
			ch.cheque_date = jvd.cheque_date
			ch.user_remark = jvd.user_remark
			ch.original_reference_type = jvd.original_reference_type
			ch.original_reference_name = jvd.original_reference_name
			ch.against_account = cstr(jvd.against_account)

			from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions
			for dimension_fieldname in get_accounting_dimensions():
				ch.set(dimension_fieldname, jvd.get(dimension_fieldname))

			ch.set(dr_or_cr, amount_in_account_currency)
			ch.set(base_dr_or_cr, amount_in_company_currency)
			ch.set(reverse_dr_or_cr, 0)
			ch.set(base_reverse_dr_or_cr, 0)

			ch.reference_type = original_reference_type
			ch.reference_name = original_reference_name
			ch.docstatus = 1

		amt_allocated += amt_allocatable
		if abs(amt_allocated - args["allocated_amount"]) < (1.0 / (10 ** (jv_detail.precision(args['dr_or_cr'])))):
			break


def reconcile_reference_in_payment_entry(args, payment_entry):
	payment_entry.setup_party_account_field()

	reference_details = {
		"reference_doctype": args.against_voucher_type,
		"reference_name": args.against_voucher,
		"total_amount": args.grand_total,
		"outstanding_amount": args.outstanding_amount,
		"allocated_amount": args.allocated_amount,
		"exchange_rate": args.exchange_rate,
	}
	if args.payment_reconciliation_journal_entry:
		reference_details.update({
			"reference_doctype": "Journal Entry",
			"reference_name": args.payment_reconciliation_journal_entry,
		})

	if args.voucher_detail_no:
		existing_row = payment_entry.get("references", {"name": args["voucher_detail_no"]})[0]
		original_row = existing_row.as_dict().copy()

		reference_details.update({
			"original_reference_doctype": existing_row.original_reference_doctype,
			"original_reference_name": existing_row.original_reference_name
		})

		existing_row.update(reference_details)
		payment_entry.set_reference_row_details(existing_row)

		if args.allocated_amount < original_row.allocated_amount:
			new_row = payment_entry.append("references")
			new_row.docstatus = 1
			for field in list(reference_details):
				new_row.set(field, original_row[field])

			new_row.allocated_amount = original_row.allocated_amount - args.allocated_amount
			payment_entry.set_reference_row_details(new_row)
	else:
		new_row = payment_entry.append("references")
		new_row.docstatus = 1
		new_row.update(reference_details)
		payment_entry.set_reference_row_details(new_row)

	payment_entry.set_amounts()


def create_payment_reconciliation_journal_entry(args, payment_doc, allocate_payment=True):
	reconcile_dr_or_cr = (
		"debit_in_account_currency"
		if args.dr_or_cr == "credit_in_account_currency"
		else "credit_in_account_currency"
	)

	posting_date = getdate(args.get("reconciliation_posting_date"))
	default_cost_center = erpnext.get_default_cost_center(args.company)

	jv = frappe.new_doc("Journal Entry")
	jv.update({
		"voucher_type": "Payment Reconciliation",
		"posting_date": posting_date,
		"company": args.company,
		"branch": payment_doc.get("branch"),
		"cost_center": default_cost_center,
		"multi_currency": 1 if args.currency != args.company_currency else 0,
		"user_remark": _("Payment Reconciliation"),
		"is_system_generated": 1,
	})

	accounting_dimensions = get_all_dimension_fields()
	for dimension_field in accounting_dimensions:
		if payment_doc.get(dimension_field):
			jv.set(dimension_field, payment_doc.get(dimension_field))

	# For Payment / Debit / Credit Note
	jv.append("accounts", {
		"account": args.account,
		"party": args.party,
		"party_type": args.party_type,
		reconcile_dr_or_cr: abs(args.allocated_amount),
		"exchange_rate": flt(args.payment_exchange_rate) or 1,
		"reference_type": args.voucher_type if allocate_payment else None,
		"reference_name": args.voucher_no if allocate_payment else None,
	})

	# Against Invoice / Outstanding Voucher
	jv.append("accounts", {
		"account": args.account,
		"party": args.party,
		"party_type": args.party_type,
		args.dr_or_cr: abs(args.allocated_amount),
		"exchange_rate": flt(args.exchange_rate) or 1,
		"reference_type": args.against_voucher_type,
		"reference_name": args.against_voucher,
	})

	# Exchange Gain / Loss
	if flt(args.difference_amount):
		jv.append("accounts", {
			"account": args.difference_account,
			"debit_in_account_currency": args.difference_amount if flt(args.difference_amount) > 0 else 0,
			"credit_in_account_currency": abs(args.difference_amount) if flt(args.difference_amount) < 0 else 0,
		})

	jv.flags.ignore_mandatory_dimension = True
	jv.submit()

	return jv.name


def unlink_voucher_from_payments(voucher_type, voucher_no, validate_permission=False):
	if validate_permission:
		allow_unlink_setting = cint(frappe.db.get_single_value("Accounts Settings", "unlink_payment_on_cancellation_of_invoice"))
		allow_unlink_role = frappe.db.get_single_value("Accounts Settings", "restrict_unlink_payments_to_role")
		has_unlink_role_permission = not allow_unlink_role or allow_unlink_role in frappe.get_roles()
		if not allow_unlink_setting or not has_unlink_role_permission:
			return

	unlink_voucher_from_journal_entry(voucher_type, voucher_no)
	unlink_voucher_from_payment_entry(voucher_type, voucher_no)

	frappe.db.sql("""
		update `tabGL Entry`
		set
			against_voucher_type = original_against_voucher_type,
			against_voucher = original_against_voucher,
			modified = %s,
			modified_by = %s
		where
			against_voucher_type = %s
			and against_voucher = %s
			and ifnull(original_against_voucher_type, '') != ''
			and ifnull(original_against_voucher, '') != ''
			and voucher_no != ifnull(against_voucher, '')
	""", (now_datetime(), frappe.session.user, voucher_type, voucher_no))

	frappe.db.sql("""
		update `tabGL Entry`
		set
			against_voucher_type = null,
			against_voucher = null,
			modified = %s,
			modified_by = %s
		where
			against_voucher_type = %s
			and against_voucher = %s
			and voucher_no != ifnull(against_voucher, '')
	""", (now_datetime(), frappe.session.user, voucher_type, voucher_no))

	frappe.db.sql("""
		update `tabGL Entry`
		set
			original_against_voucher_type = null,
			original_against_voucher = null,
			modified = %s,
			modified_by = %s
		where
			original_against_voucher_type = %s
			and original_against_voucher = %s
			and voucher_no != ifnull(against_voucher, '')
	""", (now_datetime(), frappe.session.user, voucher_type, voucher_no))


def unlink_voucher_from_journal_entry(voucher_type, voucher_no):
	linked_journal_entries = frappe.db.sql("""
		select distinct jv.name, jv.voucher_type, jv.is_system_generated, jv.docstatus
		from `tabJournal Entry Account` jvd
		inner join `tabJournal Entry` jv on jv.name = jvd.parent
		where jvd.reference_type = %s and jvd.reference_name = %s and jv.docstatus < 2
	""", (voucher_type, voucher_no), as_dict=1)

	# Cancel system generated payment reconcilation JVs
	for jv in linked_journal_entries:
		if jv.voucher_type == "Payment Reconciliation" and jv.is_system_generated and jv.docstatus == 1:
			jv_doc = frappe.get_doc("Journal Entry", jv.name)
			jv_doc.flags.ignore_permissions = True
			jv_doc.cancel()

	if linked_journal_entries:
		frappe.db.sql("""
			update `tabJournal Entry Account`
			set
				reference_type = original_reference_type,
				reference_name = original_reference_name,
				modified = %s,
				modified_by = %s
			where reference_type = %s
				and reference_name = %s
				and ifnull(original_reference_type, '') != ''
				and ifnull(original_reference_name, '') != ''
				and docstatus < 2
		""", (now_datetime(), frappe.session.user, voucher_type, voucher_no))

		frappe.db.sql("""
			update `tabJournal Entry Account`
			set
				reference_type = null,
				reference_name = null,
				modified = %s,
				modified_by = %s
			where reference_type = %s and reference_name = %s and docstatus < 2
		""", (now_datetime(), frappe.session.user, voucher_type, voucher_no))

		frappe.db.sql("""
			update `tabJournal Entry Account`
			set
				original_reference_type = null,
				original_reference_name = null,
				modified = %s,
				modified_by = %s
			where original_reference_type = %s and original_reference_name = %s and docstatus < 2
		""", (now_datetime(), frappe.session.user, voucher_type, voucher_no))

		msg_jv_list = [frappe.utils.get_link_to_form("Journal Entry", jv.name) for jv in linked_journal_entries]
		frappe.msgprint(_("Journal Entries {0} are un-linked").format(", ".join(msg_jv_list)))

		from frappe.model.document import notify_doc_update
		for name in linked_journal_entries:
			notify_doc_update("Journal Entry", name, now_datetime())

	return linked_journal_entries


def unlink_voucher_from_payment_entry(ref_type, ref_no):
	linked_payment_entries = frappe.db.sql_list("""
		select distinct parent
		from `tabPayment Entry Reference`
		where reference_doctype = %s and reference_name = %s and docstatus < 2
	""", (ref_type, ref_no))

	if linked_payment_entries:
		for pe in linked_payment_entries:
			pe_doc = frappe.get_doc("Payment Entry", pe)

			prefs = pe_doc.get("references", filters={"reference_doctype": ref_type, "reference_name": ref_no})
			for pref in prefs:
				if (
					pref.original_reference_doctype
					and pref.original_reference_name
					and (pref.original_reference_doctype, pref.original_reference_name) != (pref.reference_doctype, pref.reference_name)
				):
					pref.reference_doctype = pref.original_reference_doctype
					pref.reference_name = pref.original_reference_name
				else:
					pref.allocated_amount = 0

				pref.db_set({
					"reference_doctype": pref.reference_doctype,
					"reference_name": pref.reference_name,
					"allocated_amount": pref.allocated_amount
				})

			pe_doc.set_total_allocated_amount()
			pe_doc.set_unallocated_amount()
			pe_doc.clear_unallocated_reference_document_rows(update=True)

			pe_doc.set_user_and_timestamp()
			pe_doc.db_update()
			pe_doc.notify_update()

		msg_pe_list = [frappe.utils.get_link_to_form("Payment Entry", jv) for jv in list(set(linked_payment_entries))]
		frappe.msgprint(_("Payment Entries {0} are un-linked").format(", ".join(msg_pe_list)))

	return linked_payment_entries
