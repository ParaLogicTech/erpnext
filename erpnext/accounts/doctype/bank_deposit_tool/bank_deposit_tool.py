# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
import json

import frappe
# import frappe
from frappe.model.document import Document


class BankDepositTool(Document):
	def get_undeposited_entries_for_type(self, voucher_type, account, from_date=None, to_date=None, min_amount=None,
										 max_amount=None, limit=None):
		conditions = [
			"gle.voucher_type = %(voucher_type)s",
			"gle.account = %(account)s",
			"gle.debit > 0"
		]

		if from_date:
			conditions.append("gle.posting_date >= %(from_date)s")
		if to_date:
			conditions.append("gle.posting_date <= %(to_date)s")

		where_clause = " AND ".join(conditions)

		params = {
			"voucher_type": voucher_type,
			"account": account,
			"from_date": from_date,
			"to_date": to_date
		}

		final = []

		if voucher_type == "Journal Entry":
			# Handle standalone Journal Entries specially
			sql = f"""
				SELECT
					SUM(gle.debit) AS received_amount,
					(
						SELECT SUM(credit)
						FROM `tabGL Entry` AS credit_gl
						WHERE
							credit_gl.account = %(account)s
							AND credit_gl.against_voucher_type = 'Journal Entry'
							AND credit_gl.against_voucher IS NOT NULL
					) AS deposited_amount
				FROM `tabGL Entry` gle
				WHERE {where_clause}
				  AND gle.against_voucher IS NULL
			"""

			result = frappe.db.sql(sql, params, as_dict=True)
			if result:
				row = result[0]
				deposited = row.deposited_amount or 0
				received = row.received_amount or 0
				undeposited = received - deposited

				if undeposited > 0:
					if (min_amount and undeposited < min_amount) or (max_amount and undeposited > max_amount):
						pass
					else:
						final.append({
							"voucher_type": "Journal Entry",
							"voucher_no": "",
							"amount": undeposited
						})
		else:
			# Default logic for all other voucher types
			sql = f"""
				SELECT
					gle.voucher_type,
					gle.voucher_no,
					SUM(gle.debit) AS received_amount,
					(
						SELECT SUM(credit)
						FROM `tabGL Entry` AS credit_gl
						WHERE
							credit_gl.account = %(account)s
							AND credit_gl.against_voucher_type = gle.voucher_type
							AND credit_gl.against_voucher = gle.voucher_no
					) AS deposited_amount
				FROM `tabGL Entry` gle
				WHERE {where_clause}
				GROUP BY gle.voucher_type, gle.voucher_no
			"""

			if limit and limit > 0:
				sql += f"\nLIMIT {int(limit)}"

			results = frappe.db.sql(sql, params, as_dict=True)

			for row in results:
				deposited = row.deposited_amount or 0
				received = row.received_amount or 0
				undeposited = received - deposited

				if undeposited <= 0:
					continue

				if min_amount and undeposited < min_amount:
					continue
				if max_amount and undeposited > max_amount:
					continue

				final.append({
					"voucher_type": row.voucher_type,
					"voucher_no": row.voucher_no,
					"amount": undeposited
				})

		return final

@frappe.whitelist()
def populate_undeposited_entries(doc_name, undeposited_account):
	doc = frappe.get_doc("Bank Deposit Tool", doc_name)
	doc.set("undeposited_entries", [])

	voucher_types = [
		"Payment Entry",
		"Sales Invoice",
		"Journal Entry",
		"POS Closing Entry"
	]

	for voucher_type in voucher_types:
		entries = doc.get_undeposited_entries_for_type(
			voucher_type,
			undeposited_account,
			doc.from_date,
			doc.to_date,
			doc.minimum_pending_deposit_entry_amount,
			doc.maximum_pending_deposit_entry_amount,
			doc.limit
		)

		for row in entries:
			doc.append("undeposited_entries", {
				"voucher_type": row['voucher_type'],
				"voucher_no": row['voucher_no'],
				"amount": row['amount']
			})

	return doc

@frappe.whitelist()
def verify_account_currencies(source_account, destination_account):
	source_account = frappe.get_doc("Account", source_account)
	destination_account = frappe.get_doc("Account", destination_account)

	return source_account.account_currency == destination_account.account_currency


@frappe.whitelist()
def reconcile_undeposited_entries(source_account, deposit_account, selected_entries, deduction_entries=None,
								  company=None, remark=None, deposit_date = frappe.utils.nowdate()):
	print(deduction_entries)
	if isinstance(selected_entries, str):
		selected_entries = json.loads(selected_entries)

	if deduction_entries:
		if isinstance(deduction_entries, str):
			deduction_entries = json.loads(deduction_entries)
	else:
		deduction_entries = []

	if not source_account or not deposit_account:
		frappe.throw("Please specify both Undeposited Account and Deposit To Account.")

	if not selected_entries:
		frappe.throw("No valid undeposited entries selected to create deposit.")

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.posting_date = deposit_date
	je.company = company if company else None
	je.user_remark = remark if remark else None

	amount_deposited_to_bank = 0

	for entry in selected_entries:
		amount = entry['amount']
		# Credit line - reduce undeposited account
		je.append("accounts", {
			"account": source_account,
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
	for deduction in deduction_entries:
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
		"account": deposit_account,
		"debit_in_account_currency": amount_deposited_to_bank,
		"user_remark": "Deposited Amount to Bank"
	})

	je.insert()
	je.submit()

	return je.name

@frappe.whitelist()
def get_undeposited_entry_details(doctype, docname):
	doc = frappe.get_doc(doctype, docname)

	party = None
	cheque_number = None
	party_type = None

	if doctype == "Payment Entry":
		party = doc.party
		cheque_number = doc.reference_no
		party_type = doc.party_type

	elif doctype == "Sales Invoice":
		party_type = 'Customer'
		party = doc.customer
		cheque_number = doc.cheque_no if hasattr(doc, "cheque_no") else None

	elif doctype == "Journal Entry":
		for entry in doc.accounts:
			if entry.reference_type == "Bank Deposit Entry Management":
				continue
			if entry.party:
				party = entry.party
				break
			if entry.party_type:
				party = entry.party_type
				break

	elif doctype == "POS Closing Entry":
		party = doc.user if hasattr(doc, "user") else None
		cheque_number = None

	return {
		"party": party,
		"cheque_number": cheque_number,
		"party_type": party_type
	}
