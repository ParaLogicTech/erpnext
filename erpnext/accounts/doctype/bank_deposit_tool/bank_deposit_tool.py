# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
import json

import frappe
from frappe.model.document import Document


class BankDepositTool(Document):
	@frappe.whitelist()
	def get_undeposited_entries(self):
		# reset the undeposited entries
		self.set("undeposited_entries", [])
		self.get_undeposited_payment_entries()
		self.get_undeposited_invoice_entries()
		self.get_undeposited_journal_entries()

	def build_common_conditions_and_params(self, voucher_type, base_conditions="", base_params=None):
		if base_params is None:
			base_params = {}

		conditions = base_conditions
		params = base_params.copy()

		if self.from_date:
			if voucher_type == "Journal Entry":
				conditions += " AND gle.posting_date >= %(from_date)s"
			elif voucher_type == "Sales Invoice":
				conditions += " AND si.posting_date >= %(from_date)s"
			elif voucher_type == "Payment Entry":
				conditions += " AND posting_date >= %(from_date)s"
			params["from_date"] = self.from_date

		if self.to_date:
			if voucher_type == "Journal Entry":
				conditions += " AND gle.posting_date <= %(to_date)s"
			elif voucher_type == "Sales Invoice":
				conditions += " AND si.posting_date <= %(to_date)s"
			elif voucher_type == "Payment Entry":
				conditions += " AND posting_date <= %(to_date)s"
			params["to_date"] = self.to_date

		# Add amount filters based on voucher type
		if self.minimum_pending_deposit_entry_amount:
			if voucher_type == "Journal Entry":
				conditions += " AND gle.debit >= %(min_amount)s"
			elif voucher_type == "Sales Invoice":
				conditions += " AND sip.amount >= %(min_amount)s"
			elif voucher_type == "Payment Entry":
				conditions += " AND paid_amount >= %(min_amount)s"
			params["min_amount"] = self.minimum_pending_deposit_entry_amount

		if self.maximum_pending_deposit_entry_amount:
			if voucher_type == "Journal Entry":
				conditions += " AND gle.debit <= %(max_amount)s"
			elif voucher_type == "Sales Invoice":
				conditions += " AND sip.amount <= %(max_amount)s"
			elif voucher_type == "Payment Entry":
				conditions += " AND paid_amount <= %(max_amount)s"
			params["max_amount"] = self.maximum_pending_deposit_entry_amount

		if hasattr(self, 'limit') and self.limit:
			params["limit"] = self.limit

		return conditions, params

	def apply_limit_to_query(self, query, params):
		if params.get("limit"):
			query += " LIMIT %(limit)s"
		return query

	def get_undeposited_payment_entries(self):
		base_conditions = """
			payment_type = 'Receive'
			AND paid_to = %(account)s
			AND docstatus = 1
			AND (deposit_date IS NULL OR deposit_date = '')
		"""
		base_params = {"account": self.undeposited_account}

		conditions, params = self.build_common_conditions_and_params("Payment Entry", base_conditions, base_params)

		query = f"""
			SELECT
				'Payment Entry' AS voucher_type,
				name AS voucher_no,
				paid_amount AS amount,
				reference_no AS cheque_number,
				party,
				party_type
			from `tabPayment Entry`
			WHERE {conditions}
		"""

		query = self.apply_limit_to_query(query, params)
		entries = frappe.db.sql(query, params, as_dict=True)
		self.add_undeposited_entries(entries)

	def get_undeposited_invoice_entries(self):
		base_conditions = """
			si.docstatus = 1
			AND sip.account = %(account)s
			AND (si.deposit_date IS NULL or si.deposit_date = '')
		"""
		base_params = {"account": self.undeposited_account}

		conditions, params = self.build_common_conditions_and_params("Sales Invoice", base_conditions, base_params)

		query = f"""
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
			WHERE {conditions}
			ORDER BY si.posting_date, si.creation
		"""

		query = self.apply_limit_to_query(query, params)
		pos_sales_invoices = frappe.db.sql(query, params, as_dict=True)
		self.add_undeposited_entries(pos_sales_invoices)

	def get_undeposited_journal_entries(self):
		base_conditions = """
			gle.account = %(account)s
			AND gle.debit > 0
			AND gle.voucher_type = 'Journal Entry'
			AND gle.docstatus = 1
			AND je.docstatus = 1
			AND je.deposit_date IS NULL
		"""
		base_params = {"account": self.undeposited_account}

		conditions, params = self.build_common_conditions_and_params("Journal Entry", base_conditions, base_params)

		query = f"""
			SELECT
				'Journal Entry' AS voucher_type,
				gle.voucher_no AS voucher_no,
				gle.name AS voucher_detail_dn,
				je.cheque_no AS cheque_number,
				je.cheque_date AS cheque_date,
				gle.debit AS amount,
				gle.posting_date,
				gle.party,
				gle.party_type,
				account.account_currency AS currency
			FROM `tabGL Entry` gle
			INNER JOIN `tabJournal Entry` je ON je.name = gle.voucher_no
			INNER JOIN `tabAccount` account ON account.name = gle.account
			WHERE {conditions}
			ORDER BY gle.posting_date DESC, gle.creation DESC
		"""
		query = self.apply_limit_to_query(query, params)
		jv_entries = frappe.db.sql(query, params, as_dict=True)
		self.add_undeposited_entries(jv_entries)

	def add_undeposited_entries(self, entries):
		for row in entries:
			self.append("undeposited_entries", {
				"voucher_type": row["voucher_type"],
				"voucher_no": row["voucher_no"],
				"amount": row["amount"],
				"cheque_number": row.get("cheque_number"),
				"cheque_date": row.get("cheque_date"),
				"posting_date": row.get("posting_date"),
				"party": row.get("party"),
				"party_type": row.get("party_type")
			})

	def validate(self):
		self._validate_accounts()

	def _validate_accounts(self):
		# Ensure accounts are different
		if self.undeposited_account == self.deposit_to_account:
			frappe.throw("Undeposited Account and Deposit To Account cannot be the same")
		# ensure the account selected have same currency
		undeposited_acount = frappe.get_cached_doc("Account", self.undeposited_account);
		deposit_to_account = frappe.get_cahed_doc("Account", self.deposit_to_account);
		if undeposited_acount.currency != deposit_to_account.currency:
			frappe.throw("Undeposited Account and Deposit To Account must have same currency")


	@frappe.whitelist()
	def reconcile_undeposited_entries(self, selected_entries):
		# Validate before processing
		self.validate()

		if isinstance(selected_entries, str):
			selected_entries = json.loads(selected_entries)

		if not self.undeposited_account or not self.deposit_to_account:
			frappe.throw("Please specify both Undeposited Account and Deposit To Account.")

		if not selected_entries:
			frappe.throw("No valid undeposited entries selected to create deposit.")

		je = frappe.new_doc("Journal Entry")
		je.posting_date = self.deposit_date
		je.company = self.company
		je.user_remark = self.remarks
		# set the reference number if provided
		if self.deposit_reference_id:
			je.cheque_no = self.deposit_reference_id

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
		# update deposit dates of the vouchers
		for entry in selected_entries:
			voucher_type = entry["voucher_type"]
			voucher_no = entry["voucher_no"]
			frappe.db.set_value(voucher_type, voucher_no, "deposit_date", self.deposit_date)

		self.set("adjustment_entries", [])

		return je.name
