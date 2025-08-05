# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
import json

import frappe
from frappe.model.document import Document


class BankDepositTool(Document):
	@frappe.whitelist()
	def get_undeposited_entries(self):
		self.get_undeposited_payment_entries()
		self.get_undeposited_invoice_entries()
		self.get_undeposited_journal_entries()

	def get_undeposited_payment_entries(self):
		entries = frappe.db.sql("""
				SELECT
					'Payment Entry' AS voucher_type,
					name AS voucher_no,
					paid_amount AS amount,
					reference_no AS cheque_number,
					party
				from `tabPayment Entry`
				WHERE
					payment_type = 'Receive'
					AND paid_to = %(account)s
					AND docstatus = 1
					AND (deposit_date IS NULL OR deposit_date = '')
			""", {"account": self.undeposited_account}, as_dict=True)

		self.add_undeposited_entries(entries)

	def get_undeposited_invoice_entries(self):
		pos_sales_invoices = frappe.db.sql("""
				SELECT
					'Sales Invoice' AS voucher_type,
					si.name AS voucher_no,
					sip.name AS voucher_detail_dn,
					sip.reference_no AS cheque_number,
					sip.reference_date AS cheque_date,
					sip.amount AS amount,
					si.posting_date,
					si.customer AS party,
					'Customer' AS party_type,
					account.account_currency AS currency
				FROM `tabSales Invoice Payment` sip
				INNER JOIN `tabSales Invoice` si ON sip.parent = si.name
				INNER JOIN `tabAccount` account ON account.name = sip.account
				WHERE
					si.docstatus = 1
					AND sip.account = %(account)s
					AND (si.deposit_date IS NULL or si.deposit_date = '')
					AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
				ORDER BY si.posting_date, si.creation
			""", {
			"account": self.undeposited_account,
			"from_date": self.from_date,
			"to_date": self.to_date
		}, as_dict=True)

		self.add_undeposited_entries(pos_sales_invoices)

	def get_undeposited_journal_entries(self):
		entries = frappe.db.sql("""
			SELECT
				'Journal Entry' AS voucher_type,
				gle.voucher_no AS voucher_no,
				gle.name AS voucher_detail_dn,
				je.cheque_no AS cheque_number,
				je.cheque_date AS cheque_date,
				gle.debit AS amount,
				gle.posting_date,
				gle.party,
				account.account_currency AS currency
			FROM `tabGL Entry` gle
			INNER JOIN `tabJournal Entry` je ON je.name = gle.voucher_no
			INNER JOIN `tabAccount` account ON account.name = gle.account
			WHERE
				gle.account = %(account)s
				AND gle.debit > 0
				AND gle.voucher_type = 'Journal Entry'
				AND gle.docstatus = 1
				AND je.docstatus = 1
				AND je.deposit_date IS NULL
				AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
			ORDER BY gle.posting_date, gle.creation
		""", {
			"account": self.undeposited_account,
			"from_date": self.from_date,
			"to_date": self.to_date
		}, as_dict=True)

		self.add_undeposited_entries(entries)

	def add_undeposited_entries(self, entries):
		for row in entries:
			self.append("undeposited_entries", {
				"voucher_type": row["voucher_type"],
				"voucher_no": row["voucher_no"],
				"amount": row["amount"],
				"cheque_number": row.get("cheque_number"),
				"cheque_date": row.get("cheque_date"),
				"posting_date": row.get("posting_date"),
				"party": row.get("party")
			})


	@frappe.whitelist()
	def reconcile_undeposited_entries(self, selected_entries):

		if isinstance(selected_entries, str):
			selected_entries = json.loads(selected_entries)

		if not self.undeposited_account or not self.deposit_to_account:
			frappe.throw("Please specify both Undeposited Account and Deposit To Account.")

		if not selected_entries:
			frappe.throw("No valid undeposited entries selected to create deposit.")

		je = frappe.new_doc("Journal Entry")
		je.voucher_type = ""
		je.posting_date = self.deposit_date
		je.company = self.company
		je.user_remark = self.remarks

		amount_deposited_to_bank = 0

		for entry in selected_entries:
			amount = entry['amount']
			# Credit line - reduce undeposited account
			je.append("accounts", {
				"account": self.undeposited_account,
				"credit_in_account_currency": amount,
				"reference_type": entry['voucher_type'],
				"reference_name": entry['voucher_no'],
			})
			amount_deposited_to_bank += amount

		def get_user_remark_from_entry_type(type):
			if type == 'Transaction Fee':
				return 'Transaction Fee of the Deposit'
			elif type == 'Bank Fee':
				return 'Bank Charges for the Deposit'
			else:
				return 'Other Miscellaneous Charges for the Deposit'

		# fee amount entries
		for deduction in self.adjustment_entries:
			deduction_amount = deduction.get('adjustment_amount') or 0
			# decrease deposit to account since it is an adjustment
			je.append("accounts", {
				"account": deduction.get('account'),
				"debit_in_account_currency": deduction_amount,
				"user_remark": get_user_remark_from_entry_type(deduction.get('entry_type')),
			})
			# reduce the amount from the bank deposit
			amount_deposited_to_bank -= deduction_amount

		# Debit line - increase deposit_to account
		# bank deposit
		je.append("accounts", {
			"account": self.deposit_to_account,
			"debit_in_account_currency": amount_deposited_to_bank
		})

		je.insert()
		je.submit()

		return je.name
