# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_all_valid_dimension_fields


class BankDepositTool(Document):
	def validate(self):
		if not self.undeposited_account:
			frappe.throw(_("Please select Undeposited Account"))
		if not self.deposit_to_account:
			frappe.throw(_("Please select Deposit To Account"))
		if not self.deposit_date:
			frappe.throw(_("Deposit Date is mandatory"))

		self.validate_accounts()

	def validate_accounts(self):
		if self.undeposited_account == self.deposit_to_account:
			frappe.throw(_("Undeposited Account and Deposit To Account cannot be the same"))

		undeposited_account = frappe.get_cached_doc("Account", self.undeposited_account)
		deposit_to_account = frappe.get_cached_doc("Account", self.deposit_to_account)

		if undeposited_account.account_currency != deposit_to_account.account_currency:
			frappe.throw(_("Undeposited Account and Deposit To Account must have same currency"))

	@frappe.whitelist()
	def get_undeposited_entries(self):
		undeposited_payment_entries = self.get_undeposited_payment_entries()
		undeposited_pos_invoices = self.get_undeposited_invoice_entries()
		undeposited_journal_entries = self.get_undeposited_journal_entries()

		entries = list(undeposited_payment_entries) + list(undeposited_pos_invoices) + list(undeposited_journal_entries)

		if hasattr(self, 'limit') and self.limit:
			entries = entries[:self.limit]
		self.add_undeposited_entries(entries)

	def get_undeposited_payment_entries(self):
		conditions = ""
		params = {"account": self.undeposited_account}

		if self.from_date:
			conditions += " and posting_date >= %(from_date)s"
			params["from_date"] = self.from_date

		if self.to_date:
			conditions += " and posting_date <= %(to_date)s"
			params["to_date"] = self.to_date

		if self.minimum_pending_deposit_entry_amount:
			conditions += " and paid_amount >= %(min_amount)s"
			params["min_amount"] = self.minimum_pending_deposit_entry_amount

		if self.maximum_pending_deposit_entry_amount:
			conditions += " and paid_amount <= %(max_amount)s"
			params["max_amount"] = self.maximum_pending_deposit_entry_amount

		payment_entries = frappe.db.sql("""
			select
				'Payment Entry' as voucher_type, name as voucher_no,
				paid_amount as amount,
				reference_no as cheque_number, reference_date as cheque_date,
				posting_date,
				party_type, party, party_name
			from `tabPayment Entry`
			where
				payment_type = 'Receive'
				and paid_to = %(account)s
				and docstatus = 1
				and (deposit_date is null or deposit_date = '')
				{0}
			order by posting_date, creation
		""".format(conditions), params, as_dict=1)

		return payment_entries

	def get_undeposited_invoice_entries(self):
		conditions = ""
		params = {"account": self.undeposited_account}

		if self.from_date:
			conditions += " and si.posting_date >= %(from_date)s"
			params["from_date"] = self.from_date

		if self.to_date:
			conditions += " and si.posting_date <= %(to_date)s"
			params["to_date"] = self.to_date

		if self.minimum_pending_deposit_entry_amount:
			conditions += " and sip.amount >= %(min_amount)s"
			params["min_amount"] = self.minimum_pending_deposit_entry_amount

		if self.maximum_pending_deposit_entry_amount:
			conditions += " and sip.amount <= %(max_amount)s"
			params["max_amount"] = self.maximum_pending_deposit_entry_amount

		pos_sales_invoices = frappe.db.sql("""
			select
				'Sales Invoice' as voucher_type, si.name as voucher_no,
				'Sales Invoice Payment' as voucher_detail_dt, sip.name as voucher_detail_dn,
				sip.reference_no as cheque_number, sip.reference_date as cheque_date,
				sip.amount as amount,
				si.posting_date,
				si.customer as against_account,
				'Customer' as party_type, si.customer as party, si.customer_name as party_name,
				account.account_currency
			from `tabSales Invoice Payment` sip
			inner join `tabSales Invoice` si on sip.parent = si.name
			inner join `tabAccount` account on account.name = sip.account
			where
				si.docstatus = 1
				and sip.account = %(account)s
				and (sip.deposit_date is null or sip.deposit_date = '')
				{0}
			order by si.posting_date, si.creation
		""".format(conditions), params, as_dict=1)

		return pos_sales_invoices

	def get_undeposited_journal_entries(self):
		conditions = ""
		params = {"account": self.undeposited_account}

		if self.from_date:
			conditions += " and je.posting_date >= %(from_date)s"
			params["from_date"] = self.from_date

		if self.to_date:
			conditions += " and je.posting_date <= %(to_date)s"
			params["to_date"] = self.to_date

		if self.minimum_pending_deposit_entry_amount:
			conditions += " and jea.debit_in_account_currency >= %(min_amount)s"
			params["min_amount"] = self.minimum_pending_deposit_entry_amount

		if self.maximum_pending_deposit_entry_amount:
			conditions += " and jea.debit_in_account_currency <= %(max_amount)s"
			params["max_amount"] = self.maximum_pending_deposit_entry_amount

		journal_entries = frappe.db.sql("""
			select 
				'Journal Entry' as voucher_type, je.name as voucher_no,
				'Journal Entry Account' as voucher_detail_dt, jea.name as voucher_detail_dn,
				jea.cheque_no as cheque_number, jea.cheque_date,
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
				{0}
			order by je.posting_date, je.creation
		""".format(conditions), params, as_dict=1)

		return journal_entries

	def add_undeposited_entries(self, entries):
		self.reset_fields()
		self.set("undeposited_entries", [])
		total_undeposited_amount = 0
		for row in entries:
			self.append("undeposited_entries", {
				"voucher_type": row.get("voucher_type"),
				"voucher_no": row.get("voucher_no"),
				"voucher_detail_dt": row.get("voucher_detail_dt"),
				"voucher_detail_dn": row.get("voucher_detail_dn"),
				"amount": flt(row.get("amount", 0)),
				"cheque_number": row.get("cheque_number"),
				"cheque_date": row.get("cheque_date"),
				"posting_date": row.get("posting_date"),
				"party": row.get("party"),
				"party_type": row.get("party_type"),
				"party_name": row.get("party_name")
			})
			total_undeposited_amount += flt(row.get("amount", 0))
		self.set("undeposited_amount", total_undeposited_amount)

	def reset_fields(self):
		self.set("selected_deposit_amount", 0)
		self.set("net_deposited_amount", 0)
		self.set("difference_amount", 0)
		self.set("adjustment_entries", [])


	@frappe.whitelist()
	def reconcile_undeposited_entries(self, selected_entries):
		self.validate()

		if isinstance(selected_entries, str):
			selected_entries = json.loads(selected_entries)

		if not selected_entries:
			frappe.throw(_("No valid undeposited entries selected to create deposit"))

		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Bank Entry"
		je.company = self.company
		je.posting_date = self.deposit_date
		je.cheque_date = self.deposit_date
		je.user_remark = self.remarks or _("Bank deposit entry")

		if self.deposit_number:
			je.cheque_no = self.deposit_number

		amount_deposited_to_bank = 0

		for entry in selected_entries:
			amount = flt(entry.get('amount', 0))
			if amount <= 0:
				continue

			# Credit line - reduce undeposited account
			credit_row = je.append("accounts", {
				"account": self.undeposited_account,
				"credit_in_account_currency": amount,
				"reference_type": entry.get('voucher_type'),
				"reference_name": entry.get('voucher_no'),
				"cheque_no": entry.get('cheque_number'),
				"cheque_date": entry.get('cheque_date'),
			})

			# Add dimensions from original voucher
			additional_values = self.get_entry_additional_values(entry)
			credit_row.update(additional_values)

			amount_deposited_to_bank += amount

		# Process adjustment entries
		if self.selected_deposit_amount != self.net_deposited_amount:
			for adjustment in self.adjustment_entries:
				adjustment_amount = flt(adjustment.get('adjustment_amount', 0))
				if adjustment_amount <= 0:
					continue

				adjustment_row = je.append("accounts", {
					"account": adjustment.get('account'),
					"debit_in_account_currency": adjustment_amount,
					"user_remark": self.get_adjustment_remark(adjustment.get('entry_type')),
				})
				adjustment_dimensions = self.get_adjustment_dimensions(adjustment.get('account'))
				adjustment_row.update(adjustment_dimensions)

				amount_deposited_to_bank -= adjustment_amount

		if amount_deposited_to_bank <= 0:
			frappe.throw(_("Net deposit amount must be positive"))

		# Debit line - increase deposit_to account
		je.append("accounts", {
			"account": self.deposit_to_account,
			"debit_in_account_currency": amount_deposited_to_bank
		})

		je.insert()
		je.submit()

		# Update deposit dates
		self.update_deposit_dates(selected_entries)

		# Clear adjustment entries
		self.set("adjustment_entries", [])

		frappe.msgprint(_("Bank Deposit Entry {0} created successfully").format(
			frappe.utils.get_link_to_form("Journal Entry", je.name)
		))

		return je.name

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

	def get_adjustment_dimensions(self, account):
		dimensions = {}

		if not account:
			return dimensions

		account_doc = frappe.get_cached_doc("Account", account)

		# For Income/Expense accounts, set mandatory dimensions
		if account_doc.account_type in ['Income Account', 'Expense Account']:
			company_doc = frappe.get_cached_doc("Company", self.company)

			if company_doc.cost_center:
				dimensions["cost_center"] = company_doc.cost_center
			else:
				# Fallback: find any cost center for this company
				default_cost_center = frappe.db.get_value("Cost Center",
														  {"company": self.company, "is_group": 0}, "name")
				if default_cost_center:
					dimensions["cost_center"] = default_cost_center

		return dimensions

	def get_adjustment_remark(self, entry_type):
		remarks = {
			'Transaction Fee': _('Transaction Fee of the Deposit'),
			'Bank Fee': _('Bank Charges for the Deposit')
		}
		return remarks.get(entry_type, _('Other Miscellaneous Charges for the Deposit'))

	def update_deposit_dates(self, selected_entries):
		for row in selected_entries:
			if row.voucher_detail_dn:
				frappe.db.set_value(row.voucher_detail_dt, row.voucher_detail_dn, 'deposit_date', row.clearance_date,
						notify=True)
			else:
				frappe.db.set_value(row.voucher_type, row.voucher_no, 'deposit_date', row.clearance_date,
						notify=True)


def get_document_dimensions(doctype, name):
	dimension_fields = get_all_valid_dimension_fields(doctype)
	if frappe.get_meta(doctype).has_field("user_remark"):
		dimension_fields.append("user_remark")

	dimensions = {}
	if dimension_fields:
		dimensions = frappe.db.get_value(doctype, name, dimension_fields, as_dict=True) or {}

	dimensions = {f: v for f, v in dimensions.items() if v}
	return dimensions
