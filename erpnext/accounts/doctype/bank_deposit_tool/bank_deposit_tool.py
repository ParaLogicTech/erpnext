# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from erpnext.accounts.utils import get_balance_on
from frappe import _
from frappe.utils import flt, getdate
from frappe.model.document import Document
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_all_dimension_fields
from erpnext.accounts.doctype.bank_reconciliation.bank_reconciliation import get_document_dimensions
import json


class BankDepositTool(Document):
	def validate(self):
		self.validate_undeposited_account()
		self.validate_deposit_to_account()
		self.validate_adjustment_accounts()

	def validate_undeposited_account(self):
		if not self.undeposited_account:
			frappe.throw(_("Please select Undeposited Funds Account"))
		if not self.deposit_date:
			frappe.throw(_("Please select Deposit Date"))

		self.deposit_date = getdate(self.deposit_date)
		if self.deposit_date > getdate():
			frappe.throw(_("Deposit Date cannot be in the future"))

		undeposited_account = frappe.get_cached_doc("Account", self.undeposited_account)
		self.currency = undeposited_account.account_currency

		if undeposited_account.account_type not in ("Bank", "Cash"):
			frappe.throw(_("Undeposited Funds Account must be of type Bank or Cash"))

		self.undeposited_account_balance = get_balance_on(self.undeposited_account, self.deposit_date)

	def validate_deposit_to_account(self):
		if not self.deposit_to_account:
			frappe.throw(_("Please select Deposit To Account"))

		if self.undeposited_account == self.deposit_to_account:
			frappe.throw(_("Undeposited Funds Account and Deposit To Account cannot be the same"))

		deposit_to_account = frappe.get_cached_doc("Account", self.deposit_to_account)

		if self.undeposited_account:
			undeposited_account = frappe.get_cached_doc("Account", self.undeposited_account)
			if undeposited_account.account_currency != deposit_to_account.account_currency:
				frappe.throw(_("Undeposited Funds Account and Deposit To Account must have same currency"))

		if deposit_to_account.account_type != "Bank":
			frappe.throw(_("Deposit To account must be of type Bank"))

	def validate_adjustment_accounts(self):
		for d in self.adjustment_entries:
			if not d.account:
				continue

			adjustment_account = frappe.get_cached_doc("Account", d.account)
			if self.undeposited_account:
				undeposited_account = frappe.get_cached_doc("Account", self.undeposited_account)
				if undeposited_account.account_currency != adjustment_account.account_currency:
					frappe.throw(_("Row #{0}: Adjustment Account and Deposit To Account must have same currency").format(d.idx))

				if adjustment_account.account_type in ("Receivable", "Payable"):
					if not d.supplier:
						frappe.throw(_("Row #{0}: Supplier is mandatory for {1} Adjustment Account").format(
							d.idx, adjustment_account.account_type
						))
				else:
					if d.supplier:
						frappe.throw(_("Row #{0}: Supplier can only be selected for Payable or Receivable Adjustment Account").format(
							d.idx
						))

	@frappe.whitelist()
	def get_undeposited_entries(self):
		self.validate_undeposited_account()

		undeposited_payment_entries = self.get_undeposited_payment_entries()
		undeposited_pos_invoices = self.get_undeposited_pos_invoice_entries()
		undeposited_journal_entries = self.get_undeposited_journal_entries()

		entries = undeposited_payment_entries + undeposited_pos_invoices + undeposited_journal_entries
		if self.get("limit"):
			entries = entries[:self.limit]

		entries = sorted(entries, key=lambda d: getdate(d.get("posting_date")))

		self.selected_deposit_amount = 0
		self.actual_deposit_amount = 0
		self.difference_amount = 0
		self.undeposited_entries = []

		for row in entries:
			if not row.party_type and not row.party:
				row.party_type = row.deposit_against_party_type
				row.party = row.deposit_against_party
				row.party_name = row.deposit_against_party_name

			self.append("undeposited_entries", {
				"voucher_type": row.get("voucher_type"),
				"voucher_no": row.get("voucher_no"),
				"voucher_detail_dt": row.get("voucher_detail_dt"),
				"voucher_detail_dn": row.get("voucher_detail_dn"),
				"amount": flt(row.get("amount")),
				"mode_of_payment": row.get("mode_of_payment") or row.get("deposit_against_mode_of_payment"),
				"reference_no": row.get("reference_no"),
				"reference_date": row.get("reference_date"),
				"posting_date": row.get("posting_date"),
				"party": row.get("party"),
				"party_type": row.get("party_type"),
				"party_name": row.get("party_name"),
				"pos_profile": row.get("pos_profile"),
				"cashier": row.get("cashier"),
				"pos_closing_entry": row.get("pos_closing_entry"),
				"original_voucher_type": row.get("deposit_against_type") or row.get("voucher_type"),
				"original_voucher_no": row.get("deposit_against") or row.get("voucher_no"),
				"original_voucher_date": row.get("deposit_against_date") or row.get("posting_date"),
			})

	def get_undeposited_payment_entries(self):
		conditions = ""
		params = {"account": self.undeposited_account, "deposit_date": self.deposit_date, "limit": self.limit}

		if self.from_date:
			conditions += " and posting_date >= %(from_date)s"
			params["from_date"] = self.from_date

		if self.to_date:
			conditions += " and posting_date <= %(to_date)s"
			params["to_date"] = self.to_date

		if self.min_amount:
			conditions += " and paid_amount >= %(min_amount)s"
			params["min_amount"] = self.min_amount

		if self.max_amount:
			conditions += " and paid_amount <= %(max_amount)s"
			params["max_amount"] = self.max_amount

		limit = "limit %(limit)s" if self.limit else ""

		payment_entries = frappe.db.sql(f"""
			select
				'Payment Entry' as voucher_type,
				name as voucher_no,
				paid_amount as amount,
				mode_of_payment,
				reference_no,
				reference_date,
				posting_date,
				party_type,
				party,
				party_name,
				pos_profile,
				cashier
			from `tabPayment Entry`
			where
				payment_type = 'Receive'
				and paid_to = %(account)s
				and docstatus = 1
				and deposit_date is null
				and posting_date <= %(deposit_date)s
				{conditions}
			order by posting_date, creation
			{limit}
		""", params, as_dict=1)

		pe_map = {}
		for pe in payment_entries:
			pe_map[pe.voucher_no] = pe

		pos_closing_map = self.get_pos_closing_entries("Payment Entry", list(pe_map.keys()))
		for voucher_no, pce in pos_closing_map.items():
			if pe_map.get(voucher_no):
				pe_map[voucher_no].pos_closing_entry = pce

		return payment_entries

	def get_undeposited_pos_invoice_entries(self):
		conditions = ""
		params = {"account": self.undeposited_account, "deposit_date": self.deposit_date, "limit": self.limit}

		if self.from_date:
			conditions += " and si.posting_date >= %(from_date)s"
			params["from_date"] = self.from_date

		if self.to_date:
			conditions += " and si.posting_date <= %(to_date)s"
			params["to_date"] = self.to_date

		if self.min_amount:
			conditions += " and sip.amount >= %(min_amount)s"
			params["min_amount"] = self.min_amount

		if self.max_amount:
			conditions += " and sip.amount <= %(max_amount)s"
			params["max_amount"] = self.max_amount

		limit = "limit %(limit)s" if self.limit else ""

		pos_sales_invoices = frappe.db.sql(f"""
			select
				'Sales Invoice' as voucher_type,
				si.name as voucher_no,
				'Sales Invoice Payment' as voucher_detail_dt,
				sip.name as voucher_detail_dn,
				sip.reference_no,
				sip.reference_date,
				sip.amount,
				sip.mode_of_payment,
				si.posting_date,
				'Customer' as party_type,
				si.customer as party,
				si.customer_name as party_name,
				si.pos_profile,
				si.cashier
			from `tabSales Invoice Payment` sip
			inner join `tabSales Invoice` si on sip.parent = si.name
			inner join `tabAccount` account on account.name = sip.account
			where
				si.docstatus = 1
				and sip.account = %(account)s
				and sip.deposit_date is null
				and si.posting_date <= %(deposit_date)s
				and sip.amount != 0
				{conditions}
			order by si.posting_date, si.creation, sip.idx
			{limit}
		""", params, as_dict=1)

		si_map = {}
		voucher_nos = set()
		voucher_detail_nos = []
		for si in pos_sales_invoices:
			if si.voucher_detail_dn:
				si_map[(si.voucher_no, si.voucher_detail_dn)] = si
				voucher_nos.add(si.voucher_no)
				voucher_detail_nos.append(si.voucher_detail_dn)

		pos_closing_map = self.get_pos_closing_entries("Sales Invoice", voucher_nos, voucher_detail_nos)
		for (voucher_no, voucher_detail_no), pce in pos_closing_map.items():
			if si_map.get((voucher_no, voucher_detail_no)):
				si_map[(voucher_no, voucher_detail_no)].pos_closing_entry = pce

		return pos_sales_invoices

	def get_undeposited_journal_entries(self):
		conditions = ""
		params = {"account": self.undeposited_account, "deposit_date": self.deposit_date, "limit": self.limit}

		if self.from_date:
			conditions += " and je.posting_date >= %(from_date)s"
			params["from_date"] = self.from_date

		if self.to_date:
			conditions += " and je.posting_date <= %(to_date)s"
			params["to_date"] = self.to_date

		if self.min_amount:
			conditions += " and jea.debit_in_account_currency >= %(min_amount)s"
			params["min_amount"] = self.min_amount

		if self.max_amount:
			conditions += " and jea.debit_in_account_currency <= %(max_amount)s"
			params["max_amount"] = self.max_amount

		limit = "limit %(limit)s" if self.limit else ""

		journal_entries = frappe.db.sql(f"""
			select 
				'Journal Entry' as voucher_type,
				je.name as voucher_no,
				'Journal Entry Account' as voucher_detail_dt,
				jea.name as voucher_detail_dn,
				jea.cheque_no as reference_no,
				jea.cheque_date as reference_date,
				jea.debit_in_account_currency - jea.credit_in_account_currency as amount,
				je.mode_of_payment,
				je.posting_date,
				jea.against_account,
				jea.party_type,
				jea.party,
				jea.party_name,
				jea.account_currency,
				pce.pos_profile,
				pce.user as cashier,
				pce.name as pos_closing_entry,
				jea.deposit_against_type,
				jea.deposit_against,
				jea.deposit_against_detail_no
			from `tabJournal Entry Account` jea
			inner join `tabJournal Entry` je on jea.parent = je.name
			left join `tabPOS Closing Entry` pce on jea.reference_name = pce.name and jea.reference_type = 'POS Closing Entry'
			where
				je.docstatus = 1
				and jea.account = %(account)s
				and (jea.debit_in_account_currency - jea.credit_in_account_currency) > 0
				and jea.deposit_date is null
				and je.posting_date <= %(deposit_date)s
				and je.is_opening != 'Yes'
				{conditions}
			order by je.posting_date, je.creation, jea.idx
			{limit}
		""", params, as_dict=1)

		# Set original document info (deposited against)
		deposit_jv_map = {}
		jv_against_invoice_payments_map = {}
		for jv in journal_entries:
			if jv.deposit_against_type and jv.deposit_against:
				deposit_jv_map.setdefault((jv.deposit_against_type, jv.deposit_against), []).append(jv)
			if jv.deposit_against_type == "Sales Invoice" and jv.deposit_against_detail_no:
				jv_against_invoice_payments_map.setdefault(jv.deposit_against_detail_no, []).append(jv)

		deposit_against_data, invoice_payments_data = self.get_deposit_against_data(journal_entries)

		for d in deposit_against_data:
			for jv in deposit_jv_map.get((d.doctype, d.name), []):
				jv.deposit_against_date = d.posting_date
				jv.deposit_against_party_type = d.party_type
				jv.deposit_against_party = d.party
				jv.deposit_against_party_name = d.party_name
				jv.deposit_against_mode_of_payment = d.mode_of_payment

		for d in invoice_payments_data:
			for jv in jv_against_invoice_payments_map.get(d.name, []):
				jv.deposit_against_mode_of_payment = d.mode_of_payment

		return journal_entries

	@staticmethod
	def get_deposit_against_data(entries):
		sales_invoices = [jv.deposit_against for jv in entries if jv.deposit_against_type == "Sales Invoice"]
		invoice_payments = [jv.deposit_against_detail_no for jv in entries if jv.deposit_against_type == "Sales Invoice"]
		payment_entries = [jv.deposit_against for jv in entries if jv.deposit_against_type == "Payment Entry"]

		sales_invoice_data = []
		invoice_payments_data = []
		payment_entry_data = []

		if sales_invoices:
			sales_invoice_data = frappe.db.sql("""
				select 'Sales Invoice' as doctype, name,
					'Customer' as party_type, bill_to as party, bill_to_name as party_name,
					posting_date
				from `tabSales Invoice`
				where name in %s
			""", [sales_invoices], as_dict=1)

		if payment_entries:
			payment_entry_data = frappe.db.sql("""
				select 'Payment Entry' as doctype, name,
					party_type, party, party_name, posting_date, mode_of_payment
				from `tabPayment Entry`
				where name in %s
			""", [payment_entries], as_dict=1)

		if invoice_payments:
			invoice_payments_data = frappe.db.sql("""
				select name, mode_of_payment
				from `tabSales Invoice Payment`
				where name in %s
			""", [invoice_payments], as_dict=1)

		return sales_invoice_data + payment_entry_data, invoice_payments_data

	@staticmethod
	def get_pos_closing_entries(voucher_type, voucher_nos, voucher_detail_nos=None):
		if not voucher_nos:
			return {}

		voucher_detail_nos_condition = ""
		if voucher_detail_nos:
			voucher_detail_nos_condition = " and document_detail_no in %(voucher_detail_nos)s"

		closing_data = frappe.db.sql(f"""
			select parent as pos_closing_entry, document_name, document_detail_no
			from `tabPOS Closing Entry Detail`
			where docstatus = 1
				and document_type = %(voucher_type)s
				and document_name in %(voucher_nos)s
				{voucher_detail_nos_condition}
		""", {
			"voucher_type": voucher_type,
			"voucher_nos": voucher_nos,
			"voucher_detail_nos": voucher_detail_nos,
		}, as_dict=1)

		out = {}
		for d in closing_data:
			if voucher_detail_nos:
				out[(d.document_name, d.document_detail_no)] = d.pos_closing_entry
			else:
				out[d.document_name] = d.pos_closing_entry

		return out

	@frappe.whitelist()
	def submit_deposit_entry(self, selected_row_names):
		je = self.make_deposit_journal_entry(selected_row_names)
		je.insert()
		je.submit()

		frappe.msgprint(_("Deposit Entry {0} submitted successfully").format(
			frappe.bold(je.name)
		))

		self.get_undeposited_entries()
		self.adjustment_entries = []

		return je.name

	@frappe.whitelist()
	def make_deposit_entry(self, selected_row_names):
		je = self.make_deposit_journal_entry(selected_row_names)
		je.set_amounts_in_company_currency()
		je.set_total_debit_credit()
		je.set_party_name()
		return je

	def make_deposit_journal_entry(self, selected_row_names):
		self.validate()
		self._validate_mandatory()

		if isinstance(selected_row_names, str):
			selected_row_names = json.loads(selected_row_names)

		if not selected_row_names:
			selected_row_names = []

		selected_entries = [d for d in self.undeposited_entries if d.name in selected_row_names]
		if len(selected_entries) != len(selected_row_names):
			frappe.throw(_("Some selected undeposited entries are missing from the data provided"))

		if not selected_entries and not self.adjustment_entries:
			frappe.throw(_("Please check mark Undeposited Entries first"))

		for d in selected_entries:
			self.validate_undeposited_row(d)

		deposit_amount = 0
		for d in selected_entries:
			deposit_amount += flt(d.get("amount"))
		for d in self.adjustment_entries:
			deposit_amount -= flt(d.get("adjustment_amount"))

		if flt(deposit_amount, self.precision("actual_deposit_amount")) != flt(self.actual_deposit_amount, self.precision("actual_deposit_amount")):
			frappe.throw(_("Difference Amount must be zero, please check Actual Deposit Amount or select adjustment accounts"))

		return self.make_journal_entry(selected_entries)

	def validate_undeposited_row(self, row):
		if not row.voucher_type or not row.voucher_no:
			frappe.throw(_("Row #{0}: Voucher No is missing").format(row.idx))

		docstatus = frappe.db.get_value(row.get("voucher_type"), row.get("voucher_no"), "docstatus", for_update=True)
		if docstatus != 1:
			frappe.throw(_("Row #{0}: {1} is not submitted").format(
				row.get("idx"), frappe.get_desk_link(row.voucher_type, row.voucher_no)
			))

		if row.reference_date and getdate(self.deposit_date) < getdate(row.reference_date):
			frappe.throw(_("Row #{0}: Deposit Date {1} cannot be before Reference/Cheque Date {2}").format(
				row.idx, frappe.bold(self.get_formatted("deposit_date")), frappe.bold(row.get_formatted("reference_date"))
			))

	def make_journal_entry(self, selected_entries):
		parent_dimensions = self.get_entry_additional_values()

		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Deposit Entry"
		je.company = self.company
		je.branch = self.branch
		je.posting_date = self.deposit_date
		je.cheque_no = self.deposit_no
		je.cheque_date = self.deposit_date
		je.user_remark = self.remarks or _("Deposit Entry")
		je.update(parent_dimensions)

		# conolidated bank amount
		if self.consolidate_bank_amount:
			total_amount = flt(self.actual_deposit_amount, self.precision("actual_deposit_amount"))
			je.append("accounts", {
				"account": self.deposit_to_account,
				"debit_in_account_currency": abs(total_amount) if total_amount > 0 else 0,
				"credit_in_account_currency": abs(total_amount) if total_amount < 0 else 0,
				"cheque_no": self.deposit_no,
				"cheque_date": self.deposit_date,
			})

		# selected payment entries
		for d in selected_entries:
			amount = flt(d.get('amount'))

			debit_row = None
			if not self.consolidate_bank_amount:
				debit_row = je.append("accounts", {
					"account": self.deposit_to_account,
					"debit_in_account_currency": abs(amount) if amount > 0 else 0,
					"credit_in_account_currency": abs(amount) if amount < 0 else 0,
					"cheque_no": d.get('reference_no'),
					"cheque_date": d.get('reference_date'),
					"deposit_against_type": d.voucher_type,
					"deposit_against": d.voucher_no,
					"deposit_against_detail_no": d.voucher_detail_dn,
				})

			credit_row = je.append("accounts", {
				"account": self.undeposited_account,
				"debit_in_account_currency": abs(amount) if amount < 0 else 0,
				"credit_in_account_currency": abs(amount) if amount > 0 else 0,
				"cheque_no": d.get('reference_no'),
				"cheque_date": d.get('reference_date'),
				"deposit_date": self.deposit_date,
				"deposit_against_type": d.voucher_type,
				"deposit_against": d.voucher_no,
				"deposit_against_detail_no": d.voucher_detail_dn,
			})

			# Add dimensions from the original voucher
			additional_values = self.get_entry_additional_values(d)
			credit_row.update(additional_values)
			if debit_row:
				debit_row.update(additional_values)

			if d.pos_closing_entry:
				against = {
					"reference_type": "POS Closing Entry",
					"reference_name": d.pos_closing_entry
				}
				credit_row.update(against)
				if debit_row:
					debit_row.update(against)

			credit_row.user_remark = je.user_remark or credit_row.user_remark

		# adjustment entries
		for d in self.adjustment_entries:
			amount = flt(d.get('adjustment_amount'))
			row_dimensions = self.get_accounting_dimensions(d)

			# expense row
			je.append("accounts", {
				"account": d.get('account'),
				"party_type": "Supplier" if d.get('supplier') else None,
				"party": d.get('supplier'),
				"cost_center": d.get('cost_center'),
				"debit_in_account_currency": abs(amount) if amount > 0 else 0,
				"credit_in_account_currency": abs(amount) if amount < 0 else 0,
				**row_dimensions,
			})

			# reverse bank row
			if not self.consolidate_bank_amount:
				je.append("accounts", {
					"account": self.deposit_to_account,
					"cost_center": d.get('cost_center'),
					"debit_in_account_currency": abs(amount) if amount < 0 else 0,
					"credit_in_account_currency": abs(amount) if amount > 0 else 0,
					**row_dimensions,
				})

		return je

	def get_entry_additional_values(self, entry=None):
		entry = entry or frappe._dict()

		dimensions = self.get_accounting_dimensions(self)

		voucher_type = entry.get('voucher_type')
		voucher_no = entry.get('voucher_no')
		voucher_detail_dn = entry.get('voucher_detail_dn')

		if voucher_type and voucher_no:
			dimensions.update(get_document_dimensions(voucher_type, voucher_no, with_remarks=True))

			if voucher_detail_dn and entry.get('voucher_detail_dt'):
				child_dimensions = get_document_dimensions(entry.get('voucher_detail_dt'), voucher_detail_dn, with_remarks=True)
				dimensions.update(child_dimensions)

		return dimensions

	@staticmethod
	def get_accounting_dimensions(source):
		dimensions = frappe._dict()
		dimension_fields = get_all_dimension_fields()
		for f in dimension_fields:
			if source.get(f):
				dimensions[f] = source.get(f)

		return dimensions
