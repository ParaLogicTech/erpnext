# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import erpnext
from frappe.utils import flt
from frappe import _
from frappe.model.document import Document
from erpnext.setup.utils import get_exchange_rate
from erpnext import get_company_currency
from erpnext.stock.get_item_details import get_item_tax_template_details
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_all_dimension_fields
import json


class ExpenseEntry(Document):
	def before_print(self, print_settings=None):
		self.company_address_doc = erpnext.get_company_address_doc(self)

	def validate(self):
		self.set_missing_values()
		self.check_duplicate_bill_no()
		self.validate_accounts()
		self.validate_total_amount()
		self.validate_exchange_rate()
		self.calculate_taxes()
		self.calculate_totals()

	def before_submit(self):
		self.set_missing_bill_no_date()

	def on_submit(self):
		self.create_accounting_entries()

	def on_cancel(self):
		self.cancel_accounting_entries()

	def check_duplicate_bill_no(self):
		for row in self.accounts:
			bill_no = row.bill_no or self.bill_no
			if bill_no and row.supplier:
				exp_entrty_with_duplicate = has_duplicate_bill_no(
					bill_no,
					row.supplier,
					exclude=None if self.is_new() else self.name,
				)
				if exp_entrty_with_duplicate:
					frappe.throw(_("Row {0}: Bill No {1} for Supplier {2} already exists in {3}").format(
						row.idx, bill_no, row.supplier, ", ".join(exp_entrty_with_duplicate)
					))

	def validate_accounts(self):
		if self.payable_account and frappe.get_cached_value("Account", self.payable_account, "account_type") != 'Payable':
			frappe.throw(_("Incorrect Account Type for Payable Account {0}").format(self.payable_account))
		if self.paid_from_account and frappe.get_cached_value("Account", self.paid_from_account, "account_type") not in ['Bank', 'Cash', 'Equity']:
			frappe.throw(_("Incorrect Account Type for Paid From Account {0}").format(self.paid_from_account))

		for row in self.accounts:
			if row.supplier and not self.payable_account:
				frappe.throw(_("Row {0}: Payable Account is mandatory if supplier is provided").format(row.idx))
			if not row.supplier and not self.paid_from_account:
				frappe.throw(_("Row {0}: Paid From Account is mandatory if supplier is not provided").format(row.idx))

	def validate_total_amount(self):
		for row in self.accounts:
			if not row.total_amount:
				frappe.throw(_("Row #{0}: Total Amount cannot be 0").format(row.idx))

	def set_missing_values(self):
		company_currency = get_company_currency(self.company)
		self.payable_account_currency = frappe.get_cached_value("Account", self.payable_account, "account_currency") \
			if self.payable_account else company_currency

		if self.supplier:
			for row in self.accounts:
				row.supplier = self.supplier

	def validate_exchange_rate(self):
		company_currency = get_company_currency(self.company)
		for row in self.accounts:
			if self.payable_account_currency == company_currency:
				row.exchange_rate = 1.0
			elif not row.exchange_rate or row.exchange_rate == 1.0:
				row.exchange_rate = get_exchange_rate(self.payable_account_currency, company_currency, row.bill_date or self.transaction_date)
				if not row.exchange_rate:
					frappe.throw(_("Could not find Exchange Rate from {0} to {1} on {2}").format(
						self.payable_account_currency, company_currency, row.bill_date or self.transaction_date
					))

	def set_missing_bill_no_date(self):
		for row in self.accounts:
			if not row.bill_no and self.bill_no:
				row.bill_no = self.bill_no
			if not row.bill_date:
				row.bill_date = self.transaction_date

	def calculate_taxes(self):
		for row in self.accounts:
			row.tax_rate = get_item_tax_template_details(row.item_tax_template, args={
				"company": self.company,
				"transaction_date": row.bill_date or self.transaction_date,
			}).get("item_tax_rate")

			tax_map = json.loads(row.tax_rate or '{}')
			tax_amount = 0
			for tax_account, tax_rate in tax_map.items():
				if tax_rate:
					tax_amount += flt(row.total_amount) - flt(row.total_amount) / (1 + flt(tax_rate) / 100)

			row.tax_amount = flt(tax_amount, row.precision("tax_amount"))

	def calculate_totals(self):
		for row in self.accounts:
			row.total_amount = flt(row.total_amount, row.precision('total_amount'))
			row.base_total_amount = flt(flt(row.total_amount) * flt(row.exchange_rate), row.precision('base_total_amount'))

			row.tax_amount = flt(row.tax_amount, row.precision('tax_amount'))
			row.base_tax_amount = flt(flt(row.tax_amount) * flt(row.exchange_rate), row.precision('base_tax_amount'))

			row.expense_amount = flt(flt(row.total_amount) - flt(row.tax_amount), row.precision('expense_amount'))
			row.base_expense_amount = flt(flt(row.base_total_amount) - flt(row.base_tax_amount), row.precision('base_expense_amount'))

		total_fields = [
			['total', 'total_amount'],
			['total_tax_amount', 'tax_amount'],
			['total_expense_amount', 'expense_amount'],
		]
		for target_f, source_f in total_fields:
			self.set(target_f, flt(sum([d.get(source_f) for d in self.accounts]), self.precision(target_f)))
			self.set("base_" + target_f, flt(sum([d.get("base_" + source_f) for d in self.accounts]), self.precision("base_" + target_f)))

	def create_accounting_entries(self):
		if self.posting_method == "Single Entry on Transaction Date":
			self.create_consolidate_accounting_entries()
		else:
			self.create_multiple_accounting_entries()

	def create_multiple_accounting_entries(self):
		for row in self.accounts:
			bill_jv = None
			if row.supplier:
				bill_jv = self.create_row_bill_journal_entry(row)

			if self.paid_from_account:
				if bill_jv:
					self.create_payment_entry(bill_jv, details=row)
				else:
					self.create_row_payment_journal_entry(row)

	def create_consolidate_accounting_entries(self):
		bill_jv = None
		if self.payable_account:
			bill_jv = self.create_consolidated_bill_journal_entry()

		if self.paid_from_account:
			if bill_jv:
				suppliers = list(set([d.party for d in bill_jv.accounts if d.party_type == "Supplier" and d.party]))
				for supplier in suppliers:
					supplier_rows = [d for d in bill_jv.accounts if d.party_type == "Supplier" and d.party == supplier]
					cheque_nos = [d.cheque_no for d in supplier_rows if d.cheque_no]
					total_amount = sum([d.credit_in_account_currency - d.debit_in_account_currency for d in supplier_rows])
					base_total_amount = sum([d.credit - d.debit for d in supplier_rows])
					exchange_rate = base_total_amount / total_amount if total_amount else 0

					details = frappe._dict({
						"supplier": supplier,
						"cheque_no": cheque_nos[0] if len(cheque_nos) == 1 else None,
						"total_amount": total_amount,
						"base_total_amount": base_total_amount,
						"exchange_rate": exchange_rate,
					})
					self.create_payment_entry(bill_jv, details=details)
			else:
				self.create_consolidated_payment_journal_entry()

	def create_row_bill_journal_entry(self, row):
		bill_jv = self.make_bill_journal_entry(row)
		self.append_bill_journal_entry_rows(bill_jv, row)

		bill_jv.insert()
		bill_jv.submit()

		return bill_jv

	def create_row_payment_journal_entry(self, row, bill_jv=None):
		payment_jv = self.make_payment_journal_entry(row)
		self.append_payment_journal_entry_rows(payment_jv, row, bill_jv=bill_jv)

		payment_jv.insert()
		payment_jv.submit()

		return payment_jv

	def create_consolidated_bill_journal_entry(self):
		bill_jv = self.make_bill_journal_entry()

		for row in self.accounts:
			if not row.supplier:
				frappe.throw(_("Row #{0}: Supplier is mandatory for consolidated accrual Expense Entry").format(
					row.idx
				))

			jv_rows = self.append_bill_journal_entry_rows(bill_jv, row)
			for jv_row in jv_rows:
				jv_row.user_remark = row.remarks
				self.set_accounting_dimensions(jv_row, row_source=row)

		bill_jv.insert()
		bill_jv.submit()

		return bill_jv

	def create_consolidated_payment_journal_entry(self, bill_jv=None):
		payment_jv = self.make_payment_journal_entry()

		for row in self.accounts:
			jv_rows = self.append_payment_journal_entry_rows(payment_jv, row, bill_jv=bill_jv)
			for jv_row in jv_rows:
				jv_row.user_remark = row.remarks
				self.set_accounting_dimensions(jv_row, row_source=row)

		payment_jv.insert()
		payment_jv.submit()

		return payment_jv

	def make_bill_journal_entry(self, row=None):
		company_currency = get_company_currency(self.company)
		multi_currency = 1 if self.payable_account_currency != company_currency else 0
		bill_jv = self.make_journal_entry(multi_currency, row=row, naming_series=self.journal_entry_series)
		return bill_jv

	def make_payment_journal_entry(self, row=None):
		company_currency = get_company_currency(self.company)
		paid_from_account_currency = frappe.get_cached_value("Account", self.paid_from_account, "account_currency")
		multi_currency = 1 if paid_from_account_currency != company_currency else 0

		payment_account_type = frappe.get_cached_value("Account", self.paid_from_account, "account_type")
		naming_series = None
		if payment_account_type == "Bank":
			naming_series = self.bank_entry_series
		elif payment_account_type == "Cash":
			naming_series = self.cash_entry_series

		payment_jv = self.make_journal_entry(multi_currency, row=row, naming_series=naming_series)
		return payment_jv

	def make_journal_entry(self, multi_currency, row=None, naming_series=None):
		row = row or frappe._dict()

		jv_doc = frappe.new_doc("Journal Entry")
		jv_doc.update({
			"expense_entry_name": self.name,
			"company": self.company,
			"branch": self.branch,
			"posting_date": self.get_posting_date(row),

			"bill_no": row.bill_no or self.bill_no or self.name,
			"bill_date": row.bill_date or self.transaction_date,
			"cheque_no": row.cheque_no or row.bill_no or self.bill_no or self.name,
			"cheque_date": row.bill_date or self.transaction_date,

			"multi_currency": multi_currency,
			"user_remark": row.remarks
		})

		if naming_series:
			jv_doc.naming_series = naming_series

		self.set_accounting_dimensions(jv_doc, parent_source=self, row_source=row)

		return jv_doc

	def append_bill_journal_entry_rows(self, bill_jv, row):
		jv_rows = []
		jv_rows.append(self.append_expense_debit_entry(bill_jv, row))
		jv_rows += self.append_tax_debit_entry(bill_jv, row)
		jv_rows.append(self.append_supplier_credit_entry(bill_jv, row))
		return jv_rows

	def append_payment_journal_entry_rows(self, payment_jv, row, bill_jv=None):
		jv_rows = []

		if bill_jv:
			jv_rows.append(self.append_supplier_debit_entry(payment_jv, row, bill_jv))
		else:
			jv_rows.append(self.append_expense_debit_entry(payment_jv, row))
			jv_rows += self.append_tax_debit_entry(payment_jv, row)

		jv_rows.append(self.append_payment_credit_entry(payment_jv, row))

		return jv_rows

	def append_expense_debit_entry(self, jv_doc, row):
		expense_account_currency = frappe.get_cached_value("Account", row.expense_account, "account_currency")
		return self.normalize_debit_credit(jv_doc.append("accounts", {
			"account": row.expense_account,
			"account_currency": expense_account_currency,
			"debit_in_account_currency": row.expense_amount if self.payable_account_currency == expense_account_currency
				else row.base_expense_amount,
			"debit": row.base_expense_amount,
			"exchange_rate": row.base_expense_amount / row.expense_amount if self.payable_account_currency == expense_account_currency else 1.0,

			"cheque_no": row.bill_no or self.bill_no or row.cheque_no or self.name,
		}))

	def append_tax_debit_entry(self, jv_doc, row):
		if not row.tax_amount:
			return []

		tax_map = json.loads(row.tax_rate or '{}')
		tax_map = {acc: rate for (acc, rate) in tax_map.items() if rate}
		remaining_tax_amount = row.tax_amount

		jv_rows = []
		for i, (tax_account, tax_rate) in enumerate(tax_map.items()):
			if i == len(tax_map) - 1:
				tax_amount = flt(remaining_tax_amount, row.precision('tax_amount'))
			else:
				tax_amount = flt(flt(row.total_amount) - flt(row.total_amount) / (1 + flt(tax_rate) / 100), row.precision('tax_amount'))

			tax_account_currency = frappe.get_cached_value("Account", tax_account, "account_currency")
			if tax_amount:
				jv_row = self.normalize_debit_credit(jv_doc.append("accounts", {
					"account": tax_account,
					"account_currency": tax_account_currency,
					"debit_in_account_currency": tax_amount if self.payable_account_currency == tax_account_currency
						else row.base_tax_amount,
					"debit": row.base_tax_amount,
					"exchange_rate": row.exchange_rate if self.payable_account_currency == tax_account_currency else 1.0,

					"cheque_no": row.bill_no or self.bill_no or row.cheque_no or self.name,
				}))
				jv_rows.append(jv_row)

		return jv_rows

	def append_supplier_credit_entry(self, jv_doc, row):
		return self.normalize_debit_credit(jv_doc.append("accounts", {
			"account": self.payable_account,
			"account_currency": self.payable_account_currency,
			"party_type": "Supplier",
			"party": row.supplier,
			"credit_in_account_currency": flt(row.total_amount),
			"credit": flt(row.base_total_amount),
			"exchange_rate": row.exchange_rate,

			"cheque_no": row.bill_no or self.bill_no or row.cheque_no or self.name,
		}))

	def append_supplier_debit_entry(self, jv_doc, row, bill_jv):
		return self.normalize_debit_credit(jv_doc.append("accounts", {
			"account": self.payable_account,
			"account_currency": self.payable_account_currency,
			"party_type": "Supplier",
			"party": row.supplier,
			"debit_in_account_currency": flt(row.total_amount),
			"debit": flt(row.base_total_amount),
			"exchange_rate": row.exchange_rate,
			"reference_type": "Journal Entry",
			"reference_name": bill_jv.name
		}))

	def append_payment_credit_entry(self, jv_doc, row):
		paid_from_account_currency = frappe.get_cached_value("Account", self.paid_from_account, "account_currency")
		return self.normalize_debit_credit(jv_doc.append("accounts", {
			"account": self.paid_from_account,
			"account_currency": paid_from_account_currency,
			"credit_in_account_currency": row.total_amount if self.payable_account_currency == paid_from_account_currency
				else row.base_total_amount,
			"credit": row.base_total_amount,
			"exchange_rate": row.exchange_rate if self.payable_account_currency == paid_from_account_currency else 1.0,
		}))

	@staticmethod
	def normalize_debit_credit(jv_row):
		if flt(jv_row.debit_in_account_currency) - flt(jv_row.credit_in_account_currency) < 0:
			jv_row.credit_in_account_currency = flt(jv_row.credit_in_account_currency) - flt(jv_row.debit_in_account_currency)
			jv_row.credit = flt(jv_row.credit) - flt(jv_row.debit)
			jv_row.debit_in_account_currency = 0
			jv_row.debit = 0
		else:
			jv_row.debit_in_account_currency = flt(jv_row.debit_in_account_currency) - flt(jv_row.credit_in_account_currency)
			jv_row.debit = flt(jv_row.debit) - flt(jv_row.credit)
			jv_row.credit_in_account_currency = 0
			jv_row.credit = 0

		return jv_row

	def create_payment_entry(self, bill_jv, details=None):
		paid_from_account_currency = frappe.get_cached_value("Account", self.paid_from_account, "account_currency")
		company_currency = get_company_currency(self.company)
		details = details or frappe._dict()

		pe_doc = frappe.new_doc("Payment Entry")
		pe_doc.update({
			"expense_entry_name": self.name,
			"company": self.company,
			"branch": self.branch,
			"posting_date": self.get_posting_date(details),

			"reference_no": details.cheque_no or details.bill_no or self.bill_no or self.name,
			"reference_date": details.bill_date or self.transaction_date,
			"user_remark": details.remarks,

			"payment_type": "Pay",
			"party_type": "Supplier",
			"party": details.supplier,
			"mode_of_payment": self.mode_of_payment,

			"paid_from": self.paid_from_account,
			"paid_amount": details.total_amount if paid_from_account_currency == self.payable_account_currency else details.base_total_amount,
			"base_paid_amount": details.base_total_amount,
			"source_exchange_rate": details.exchange_rate if paid_from_account_currency == self.payable_account_currency else 1.0,

			"paid_to": self.payable_account,
			"received_amount": details.total_amount,
			"base_received_amount": details.base_total_amount,
			"target_exchange_rate": details.exchange_rate,
		})

		if bill_jv:
			pe_doc.append("references", {
				"reference_doctype": "Journal Entry",
				"reference_name": bill_jv.name,
				"allocated_amount": details.base_total_amount if self.payable_account_currency == company_currency else details.total_amount,
			})

		self.set_accounting_dimensions(pe_doc, parent_source=self, row_source=details)

		pe_doc.insert()
		pe_doc.submit()

		return pe_doc

	def set_accounting_dimensions(self, target, parent_source=None, row_source=None):
		parent_source = parent_source or frappe._dict()
		row_source = row_source or frappe._dict()

		if not hasattr(self, 'acccounting_dimensions'):
			self.accounting_dimensions = get_all_dimension_fields()
			self.accounting_dimensions = list(set(self.accounting_dimensions))

		for dimension in self.accounting_dimensions:
			target.set(dimension, row_source.get(dimension) or parent_source.get(dimension))

	def get_posting_date(self, row=None):
		row = row or frappe._dict()
		if self.posting_method == "Multiple Entries on Bill Date":
			return row.bill_date or self.transaction_date
		else:
			return self.transaction_date

	def cancel_accounting_entries(self):
		self.cancel_payment_entries()
		self.cancel_journal_entries()

	def cancel_journal_entries(self):
		je_names = frappe.get_all(
			"Journal Entry",
			fields=['name', 'docstatus'],
			filters={"expense_entry_name": self.name, "docstatus": 1},
			pluck="name"
		)

		cancel_later = []
		for name in je_names:
			jv_doc = frappe.get_doc("Journal Entry", name)
			for row in jv_doc.accounts:
				if row.reference_type == "Journal Entry" and row.reference_name in je_names:
					jv_doc.cancel()
					break

			if jv_doc.docstatus == 1:
				cancel_later.append(jv_doc)

		for jv_doc in cancel_later:
			jv_doc.cancel()

	def cancel_payment_entries(self):
		pe_names = frappe.get_all(
			"Payment Entry",
			fields=['name', 'docstatus'],
			filters={"expense_entry_name": self.name, "docstatus": 1},
			pluck="name"
		)

		for name in pe_names:
			pe_doc = frappe.get_doc("Payment Entry", name)
			pe_doc.cancel()


@frappe.whitelist()
def has_duplicate_bill_no(bill_no, supplier, exclude=None):
	exclude_condition = ""
	if exclude:
		exclude_condition = "and name != %(exclude)s".format(exclude)

	data = frappe.db.sql_list(f"""
		select distinct expd.parent
		from `tabExpense Entry Detail` as expd
		where
			expd.bill_no = %(bill_no)s
			and expd.supplier = %(supplier)s
			and expd.docstatus = 1
			{exclude_condition}
	""", {
		"bill_no": bill_no,
		"supplier": supplier,
		"exclude": exclude,
	})

	return data


@frappe.whitelist()
def get_supplier_details(supplier):
	out = frappe._dict()

	supplier_doc = frappe.get_cached_doc("Supplier", supplier) if supplier else frappe._dict()
	out.supplier_name = supplier_doc.supplier_name
	out.expense_account = supplier_doc.expense_account

	return out


@frappe.whitelist()
def get_exchange_rates(bill_dates, from_currency, to_currency):
	if isinstance(bill_dates, str):
		bill_dates = json.loads(bill_dates)

	bill_dates = set(bill_dates)
	out = {}
	for date in bill_dates:
		out[date] = get_exchange_rate(from_currency, to_currency, date)

	return out
