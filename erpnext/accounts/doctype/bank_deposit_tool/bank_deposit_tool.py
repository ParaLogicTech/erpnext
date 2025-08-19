# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from erpnext.accounts.utils import get_balance_on
from frappe import _
from frappe.utils import flt, getdate
from frappe.model.document import Document
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
			self.append("undeposited_entries", {
				"voucher_type": row.get("voucher_type"),
				"voucher_no": row.get("voucher_no"),
				"voucher_detail_dt": row.get("voucher_detail_dt"),
				"voucher_detail_dn": row.get("voucher_detail_dn"),
				"amount": flt(row.get("amount")),
				"reference_no": row.get("reference_no"),
				"reference_date": row.get("reference_date"),
				"posting_date": row.get("posting_date"),
				"party": row.get("party"),
				"party_type": row.get("party_type"),
				"party_name": row.get("party_name")
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
				reference_no,
				reference_date,
				posting_date,
				party_type,
				party,
				party_name
			from `tabPayment Entry`
			where
				payment_type = 'Receive'
				and paid_to = %(account)s
				and docstatus = 1
				and (deposit_date is null or deposit_date = '')
				and posting_date <= %(deposit_date)s
				{conditions}
			order by posting_date, creation
			{limit}
		""", params, as_dict=1)

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
				si.posting_date,
				'Customer' as party_type,
				si.customer as party,
				si.customer_name as party_name
			from `tabSales Invoice Payment` sip
			inner join `tabSales Invoice` si on sip.parent = si.name
			inner join `tabAccount` account on account.name = sip.account
			where
				si.docstatus = 1
				and sip.account = %(account)s
				and (sip.deposit_date is null or sip.deposit_date = '')
				and si.posting_date <= %(deposit_date)s
				{conditions}
			order by si.posting_date, si.creation, sip.idx
			{limit}
		""", params, as_dict=1)

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
				'Journal Entry' as voucher_type, je.name as voucher_no,
				'Journal Entry Account' as voucher_detail_dt, jea.name as voucher_detail_dn,
				jea.cheque_no as reference_no, jea.cheque_date as reference_date,
				jea.debit_in_account_currency as amount,
				je.posting_date, jea.against_account,
				jea.party_type, jea.party, jea.party_name,
				jea.account_currency
			from `tabJournal Entry Account` jea
			inner join `tabJournal Entry` je on jea.parent = je.name
			where
				je.docstatus = 1
				and jea.account = %(account)s
				and jea.debit_in_account_currency > 0
				and (jea.deposit_date is null or jea.deposit_date = '')
				and je.posting_date <= %(deposit_date)s
				and je.is_opening != 'Yes'
				{conditions}
			order by je.posting_date, je.creation, jea.idx
			{limit}
		""", params, as_dict=1)

		return journal_entries

	@frappe.whitelist()
	def submit_deposit(self, selected_row_names):
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

		je = self.make_journal_entry(selected_entries)
		je.flags.ignore_mandatory = True
		je.insert()
		je.submit()

		frappe.msgprint(_("Deposit Entry {0} created successfully").format(
			frappe.utils.get_link_to_form("Journal Entry", je.name)
		))

		self.get_undeposited_entries()
		self.adjustment_entries = []

		return je.name

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
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Deposit Entry"
		je.company = self.company
		je.branch = self.branch
		je.posting_date = self.deposit_date
		je.cheque_no = self.deposit_no
		je.cheque_date = self.deposit_date
		je.user_remark = self.remarks or _("Deposit Entry")

		# selected payment entries
		for d in selected_entries:
			amount = flt(d.get('amount'))

			debit_row = je.append("accounts", {
				"account": self.deposit_to_account,
				"debit_in_account_currency": abs(amount) if amount > 0 else 0,
				"credit_in_account_currency": abs(amount) if amount < 0 else 0,
				"cheque_no": d.get('reference_no'),
				"cheque_date": d.get('reference_date'),
				"deposit_date": self.deposit_date,
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

			# Add dimensions from original voucher
			additional_values = self.get_entry_additional_values(d)
			debit_row.update(additional_values)
			credit_row.update(additional_values)

			credit_row.user_remark = je.user_remark or credit_row.user_remark

		# adjustment entries
		for d in self.adjustment_entries:
			amount = flt(d.get('adjustment_amount'))

			# expense row
			je.append("accounts", {
				"account": d.get('account'),
				"cost_center": d.get('cost_center'),
				"debit_in_account_currency": abs(amount) if amount > 0 else 0,
				"credit_in_account_currency": abs(amount) if amount < 0 else 0,
				"user_remark": _("Deposit Adjustment"),
				"deposit_date": self.deposit_date,
			})

			# bank row
			je.append("accounts", {
				"account": self.deposit_to_account,
				"cost_center": d.get('cost_center'),
				"debit_in_account_currency": abs(amount) if amount < 0 else 0,
				"credit_in_account_currency": abs(amount) if amount > 0 else 0,
				"user_remark": _("Deposit Adjustment"),
				"deposit_date": self.deposit_date,
			})

		return je

	def get_entry_additional_values(self, entry):
		dimensions = {}
		voucher_type = entry.get('voucher_type')
		voucher_no = entry.get('voucher_no')
		voucher_detail_dn = entry.get('voucher_detail_dn')

		if voucher_type and voucher_no:
			dimensions = self.get_parent_document_dimensions(voucher_type, voucher_no)

			if voucher_detail_dn and entry.get('voucher_detail_dt'):
				child_dimensions = get_document_dimensions(entry.get('voucher_detail_dt'), voucher_detail_dn)
				dimensions.update(child_dimensions)

		return dimensions

	def get_parent_document_dimensions(self, voucher_type, voucher_no):
		if not self.get("_parent_document_dimensions"):
			self._parent_document_dimensions = {}

		key = (voucher_type, voucher_no)
		if key not in self._parent_document_dimensions:
			dimensions = get_document_dimensions(voucher_type, voucher_no)
			self._parent_document_dimensions[key] = dimensions

		return self._parent_document_dimensions[key]
