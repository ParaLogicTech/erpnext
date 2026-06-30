# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, add_days
from frappe.model.document import Document
from erpnext.accounts.utils import get_balance_on
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_document_dimensions


class BankReconciliation(Document):
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

	def validate_reconciliation(self):
		if not self.bank_account:
			frappe.throw(_("Please select Bank Account"))
		if not self.from_date or not self.to_date:
			frappe.throw(_("Opening Date and Closing Date are mandatory"))

		bank_account = frappe.get_doc("Bank Account", self.bank_account)
		if not bank_account.is_company_account:
			frappe.throw(_("Bank Account {0} is not a company account").format(self.bank_account))

		self.company = bank_account.company
		self.account = bank_account.account
		self.suspense_account = bank_account.suspense_account
		if not self.account:
			frappe.throw(_("{0} does not have a GL Account configured").format(
				frappe.get_desk_link("Bank Account", self.bank_account)
			))

		self._validate_mandatory()

	@frappe.whitelist()
	def set_payment_entries(self):
		self.validate_reconciliation()
		self.opening_balance = get_opening_balance(self.bank_account, self.from_date)
		self.last_clearance_date = get_last_clearance_date(self.bank_account)

		entries = self.get_uncleared_entries()
		self.set('payment_entries', [])
		for row in entries:
			row.amount = flt(row.get('debit', 0)) - flt(row.get('credit', 0))

			if not row.party_type and not row.party:
				row.party_type = row.deposit_against_party_type
				row.party = row.deposit_against_party
				row.party_name = row.deposit_against_party_name

			self.append('payment_entries', row)

	def get_uncleared_entries(self):
		account = self.suspense_account or self.account

		if self.allow_corrections:
			clearance_condition = "and ({0}clearance_date is null or {0}clearance_date between %(from)s and %(to)s or posting_date >= %(from)s)"
		else:
			clearance_condition = "and {0}clearance_date is null"

		journal_entries = self.get_uncleared_journal_entries(account, clearance_condition)
		payment_entries = self.get_uncleared_payment_entries(account, clearance_condition)
		pos_sales_invoices = self.get_uncleared_pos_sales_invoices(account, clearance_condition)
		paid_purchase_invoices = self.get_uncleared_paid_purchase_invoices(account, clearance_condition)

		entries = payment_entries + journal_entries + pos_sales_invoices + paid_purchase_invoices
		entries = sorted(entries, key=lambda k: getdate(k.posting_date) or getdate())

		return entries

	def get_uncleared_journal_entries(self, account, clearance_condition):
		journal_entries = frappe.db.sql(f"""
			select 
				'Journal Entry' as voucher_type,
				je.name as voucher_no,
				'Journal Entry Account' as voucher_detail_dt,
				jea.name as voucher_detail_dn,
				jea.cheque_no as cheque_number,
				jea.cheque_date,
				jea.debit_in_account_currency as debit,
				jea.credit_in_account_currency as credit,
				je.posting_date,
				jea.against_account,
				jea.clearance_date,
				jea.account_currency,
				jea.party_type,
				jea.party,
				jea.party_name,
				jea.deposit_against_type,
				jea.deposit_against,
				jea.deposit_against_detail_no
			from `tabJournal Entry Account` jea
			inner join `tabJournal Entry` je on jea.parent = je.name
			where
				je.docstatus = 1
				and je.voucher_type != 'Bank Clearance Entry'
				and ifnull(je.is_opening, 'No') = 'No'
				and je.posting_date <= %(to)s
				and jea.account = %(account)s
				{clearance_condition.format('jea.')}
			order by je.posting_date, je.creation
		""", {
			"account": account, "from": self.from_date, "to": self.to_date
		}, as_dict=1)

		# Set original document info (deposited against)
		deposit_jv_map = {}
		for jv in journal_entries:
			if jv.deposit_against_type and jv.deposit_against:
				deposit_jv_map.setdefault((jv.deposit_against_type, jv.deposit_against), []).append(jv)

		deposit_against_data = self.get_deposit_against_data(journal_entries)

		for d in deposit_against_data:
			for jv in deposit_jv_map.get((d.doctype, d.name), []):
				jv.deposit_against_date = d.posting_date
				jv.deposit_against_party_type = d.party_type
				jv.deposit_against_party = d.party
				jv.deposit_against_party_name = d.party_name

		return journal_entries

	@staticmethod
	def get_deposit_against_data(entries):
		sales_invoices = [jv.deposit_against for jv in entries if jv.deposit_against_type == "Sales Invoice"]
		payment_entries = [jv.deposit_against for jv in entries if jv.deposit_against_type == "Payment Entry"]

		sales_invoice_data = []
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
					party_type, party, party_name, posting_date
				from `tabPayment Entry`
				where name in %s
			""", [payment_entries], as_dict=1)

		return sales_invoice_data + payment_entry_data

	def get_uncleared_payment_entries(self, account, clearance_condition):
		return frappe.db.sql(f"""
			select
				'Payment Entry' as voucher_type,
				name as voucher_no,
				reference_no as cheque_number,
				reference_date as cheque_date,
				if(paid_from=%(account)s, 0, received_amount) as debit,
				if(paid_from=%(account)s, paid_amount, 0) as credit,
				posting_date,
				if(paid_from=%(account)s, paid_to, paid_from) as against_account,
				if(paid_to=%(account)s, paid_to_account_currency, paid_from_account_currency) as account_currency,
				clearance_date,
				party_type,
				party,
				party_name
			from `tabPayment Entry`
			where
				docstatus = 1
				and posting_date <= %(to)s
				and (paid_from = %(account)s or paid_to = %(account)s)
				{clearance_condition.format('')}
			order by posting_date, creation
		""", {
			"account": account, "from": self.from_date, "to": self.to_date
		}, as_dict=1)

	def get_uncleared_pos_sales_invoices(self, account, clearance_condition):
		return frappe.db.sql(f"""
			select
				'Sales Invoice' as voucher_type,
				si.name as voucher_no,
				'Sales Invoice Payment' as voucher_detail_dt,
				sip.name as voucher_detail_dn,
				sip.reference_no as cheque_number,
				sip.reference_date as cheque_date,
				sip.amount as debit, 0 as credit,
				si.posting_date,
				si.debit_to as against_account,
				'Customer' as party_type,
				si.customer as party,
				si.customer_name as party_name,
				sip.clearance_date,
				account.account_currency
			from `tabSales Invoice Payment` sip
			inner join `tabSales Invoice` si on sip.parent = si.name
			inner join `tabAccount` account on account.name = sip.account
			where
				si.docstatus=1
				and sip.account = %(account)s
				and si.posting_date <= %(to)s
				{clearance_condition.format('sip.')}
			order by si.posting_date, si.creation
		""", {
			"account": account, "from": self.from_date, "to": self.to_date
		}, as_dict=1)

	def get_uncleared_paid_purchase_invoices(self, account, clearance_condition):
		return frappe.db.sql(f"""
			select
				'Purchase Invoice' as voucher_type,
				pi.name as voucher_no,
				pi.paid_amount as credit,
				0 as debit,
				pi.posting_date,
				pi.credit_to as against_account,
				'Supplier' as party_type,
				pi.supplier as party,
				pi.supplier_name as party_name,
				pi.clearance_date,
				account.account_currency
			from `tabPurchase Invoice` pi
			inner join `tabAccount` account on account.name = pi.cash_bank_account
			where
				pi.docstatus = 1
				and pi.cash_bank_account = %(account)s
				and pi.posting_date <= %(to)s
				{clearance_condition.format('pi.')}
			order by pi.posting_date, pi.creation
		""", {
			"account": account, "from": self.from_date, "to": self.to_date
		}, as_dict=1)

	@frappe.whitelist()
	def update_clearance(self):
		self.validate_reconciliation()

		if not self.payment_entries:
			frappe.throw(_("No Payment Entries to update"))

		clearance_updated = False
		for d in self.get('payment_entries'):
			self.validate_payment_row(d)
			if d.clearance_date or self.allow_corrections:
				if self.update_row_clearance_date(d):
					clearance_updated = True

		if clearance_updated:
			if self.suspense_account:
				self.create_clearance_journal_entries()

			frappe.msgprint(_("Clearance Dates Updated"))
		else:
			frappe.msgprint(_("Clearance Dates not updated"))

		self.set_payment_entries()

	def validate_payment_row(self, row):
		if not row.voucher_type or not row.voucher_no:
			frappe.throw(_("Row #{0}: Voucher No is missing").format(row.idx))

		docstatus = frappe.db.get_value(row.voucher_type, row.voucher_no, "docstatus", for_update=True)
		if docstatus != 1:
			frappe.throw(_("Row #{0}: {1} is not submitted").format(
				row.idx, frappe.get_desk_link(row.voucher_type, row.voucher_no)
			))

		row.clearance_date = getdate(row.clearance_date) if row.clearance_date else None

		if row.clearance_date:
			if row.clearance_date > getdate():
				frappe.throw(_("Row #{0}: Clearance Date {1} cannot be in the future").format(
					row.idx, frappe.bold(row.get_formatted("clearance_date"))
				))

			if row.clearance_date > getdate(self.to_date) and not self.allow_corrections:
				frappe.throw(_(
					"Row #{0}: Clearance Date {1} is greater than the 'Closing Date'. "
					"To set Clearance Date after Closing Date please check mark 'Allow Corrections' then confirm."
				).format(
					row.idx, frappe.bold(row.get_formatted("clearance_date"))
				))

			if row.clearance_date < getdate(self.from_date) and not self.allow_corrections:
				frappe.throw(_(
					"Row #{0}: Clearance Date {1} is less than the 'Opening Date'. "
					"To set Clearance Date before Opening Date please check mark 'Allow Corrections' then confirm."
				).format(
					row.idx, frappe.bold(row.get_formatted("clearance_date"))
				))

		if row.voucher_detail_dn:
			row.previous_clearance_date = frappe.db.get_value(row.voucher_detail_dt, row.voucher_detail_dn,
				'clearance_date', for_update=True)
		else:
			row.previous_clearance_date = frappe.db.get_value(row.voucher_type, row.voucher_no,
				'clearance_date', for_update=True)
		row.previous_clearance_date = getdate(row.previous_clearance_date) if row.previous_clearance_date else None

		if (
			not self.allow_corrections
			and row.previous_clearance_date
			and row.clearance_date
			and row.previous_clearance_date != row.clearance_date
		):
			frappe.throw(_("Row #{0}: {1} is already cleared").format(
				row.idx, frappe.get_desk_link(row.voucher_type, row.voucher_no)
			))

		if row.clearance_date and row.cheque_date and row.clearance_date < getdate(row.cheque_date):
			frappe.throw(_("Row #{0}: Clearance Date {1} cannot be before Reference/Cheque Date {2}").format(
				row.idx, frappe.bold(row.get_formatted("clearance_date")), frappe.bold(row.get_formatted("cheque_date"))
			))

	def update_row_clearance_date(self, row):
		if row.clearance_date == row.previous_clearance_date:
			return False

		if row.voucher_detail_dn:
			frappe.db.set_value(row.voucher_detail_dt, row.voucher_detail_dn, 'clearance_date', row.clearance_date,
				notify=True)
		else:
			frappe.db.set_value(row.voucher_type, row.voucher_no, 'clearance_date', row.clearance_date,
				notify=True)

		frappe.get_doc({
			"doctype": "Comment",
			"comment_type": "Label",
			"comment_email": frappe.session.user,
			"reference_doctype": row.voucher_type,
			"reference_name": row.voucher_no,
			"content": _("Set Clearance Date to {0}".format(
				frappe.utils.formatdate(row.clearance_date) if row.clearance_date else "None"
			)),
		}).insert(ignore_permissions=True)

		return True

	def create_clearance_journal_entries(self):
		if not self.company:
			frappe.throw(_("Company is mandatory"))

		to_clear_map = {}
		to_reverse_map = {}
		for d in self.get('payment_entries'):
			if d.clearance_date != d.previous_clearance_date:
				if d.clearance_date:
					to_clear_map.setdefault(d.clearance_date, []).append(d)
				if d.previous_clearance_date:
					to_reverse_map.setdefault(d.previous_clearance_date, []).append(d)

		reversal_jvs = []
		for clearance_date, rows in to_reverse_map.items():
			je = self.make_clearance_journal_entry(clearance_date, rows, is_reversal=True)
			je.is_system_generated = 1
			je.flags.ignore_mandatory = True
			je.save()
			je.submit()
			reversal_jvs.append(je.name)

		clearance_jvs = []
		for clearance_date, rows in to_clear_map.items():
			je = self.make_clearance_journal_entry(clearance_date, rows, is_reversal=False)
			je.is_system_generated = 1
			je.flags.ignore_mandatory = True
			je.save()
			je.submit()
			clearance_jvs.append(je.name)

		if reversal_jvs:
			frappe.msgprint(_("Clearing Reversal Journal Entries created:<br>{0}").format(
				", ".join([frappe.utils.get_link_to_form("Journal Entry", name) for name in reversal_jvs])
			))

		if clearance_jvs:
			frappe.msgprint(_("Bank Clearing Journal Entries created:<br>{0}").format(
				", ".join([frappe.utils.get_link_to_form("Journal Entry", name) for name in clearance_jvs])
			))

	def make_clearance_journal_entry(self, clearance_date, rows, is_reversal=False):
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Bank Clearance Entry"
		je.company = self.company
		je.branch = self.branch
		je.posting_date = clearance_date

		if is_reversal:
			je.user_remark = _("Bank reconciliation correction reversal entry")
		else:
			je.user_remark = _("Bank reconciliation clearance entry")

		for d in rows:
			amount = d.amount
			if is_reversal:
				amount = -amount

			bank_row = je.append("accounts", {
				"account": self.account,
				"debit_in_account_currency": abs(amount) if amount > 0 else 0,
				"credit_in_account_currency": abs(amount) if amount < 0 else 0,
				"cheque_no": d.cheque_number,
				"cheque_date": d.cheque_date,
				"clearance_date": clearance_date,
				"clear_against_type": d.voucher_type,
				"clear_against": d.voucher_no,
				"clear_against_detail_type": d.voucher_detail_dt,
				"clear_against_detail_name": d.voucher_detail_dn,
				"is_reversal": is_reversal
			})

			suspense_row = je.append("accounts", {
				"account": self.suspense_account,
				"debit_in_account_currency": abs(amount) if amount < 0 else 0,
				"credit_in_account_currency": abs(amount) if amount > 0 else 0,
				"cheque_no": d.cheque_number,
				"cheque_date": d.cheque_date,
				"clearance_date": clearance_date,
				"clear_against_type": d.voucher_type,
				"clear_against": d.voucher_no,
				"clear_against_detail_type": d.voucher_detail_dt,
				"clear_against_detail_name": d.voucher_detail_dn,
				"is_reversal": is_reversal
			})

			additional_values = self.get_row_additional_values(d)
			bank_row.update(additional_values)
			suspense_row.update(additional_values)

		return je

	@staticmethod
	def get_row_additional_values(row):
		dimensions = get_document_dimensions(row.voucher_type, row.voucher_no, with_remarks=True)
		if row.voucher_detail_dn:
			dimensions.update(get_document_dimensions(row.voucher_detail_dt, row.voucher_detail_dn, with_remarks=True))

		return dimensions


@frappe.whitelist()
def get_opening_balance(bank_account, from_date):
	if not bank_account or not from_date:
		return 0

	bank_account_doc = frappe.get_cached_doc("Bank Account", bank_account)
	account = bank_account_doc.account
	suspense_account = bank_account_doc.suspense_account

	if not account:
		return 0

	opening_date = getdate(from_date)
	prev_closing_date = add_days(opening_date, -1)

	if suspense_account:
		return get_balance_on(account, date=prev_closing_date)
	else:
		return get_bank_statement_aggregate("balance", account, date=prev_closing_date)


@frappe.whitelist()
def get_last_clearance_date(bank_account):
	if not bank_account:
		return None

	bank_account_doc = frappe.get_cached_doc("Bank Account", bank_account)
	account = bank_account_doc.account
	suspense_account = bank_account_doc.suspense_account
	if not account and not suspense_account:
		return None

	return get_bank_statement_aggregate("last_clearance_date", suspense_account or account)


def get_bank_statement_aggregate(value_type, account, date=None):
	date = getdate(date) if date else None

	args = {
		"account": account,
		"date": date,
	}

	if value_type == "balance":
		jv_select = "sum(jvd.debit_in_account_currency - jvd.credit_in_account_currency)"
		pe_select = "sum(if(paid_from = %(account)s, -paid_amount_after_tax, received_amount_after_tax))"
		si_select = "sum(sip.amount)"
		pi_select = "sum(paid_amount)"
	elif value_type == "last_clearance_date":
		jv_select = "max(jvd.clearance_date)"
		pe_select = "max(clearance_date)"
		si_select = "max(sip.clearance_date)"
		pi_select = "max(clearance_date)"
	else:
		frappe.throw(_("Invalid value_type"))

	if date:
		date_condition = "and {0}clearance_date <= %(date)s"
	else:
		date_condition = "and {0}clearance_date is not null"

	if date:
		jv_conditions = "and (jv.is_opening = 'Yes' or jvd.clearance_date <= %(date)s)"
	else:
		jv_conditions = "and (jv.is_opening = 'Yes' or jvd.clearance_date is not null)"

	if value_type == "last_clearance_date":
		jv_conditions += " and jv.voucher_type != 'Bank Clearance Entry'"

	jv_value = frappe.db.sql(f"""
		select {jv_select}
		from `tabJournal Entry Account` jvd
		inner join `tabJournal Entry` jv on jv.name = jvd.parent
		where jv.docstatus = 1 and jvd.account = %(account)s {jv_conditions}
	""", args)

	pe_value = frappe.db.sql(f"""
		select {pe_select}
		from `tabPayment Entry`
		where docstatus = 1 and (paid_from = %(account)s or paid_to = %(account)s) {date_condition.format('')}
	""", args)

	si_value = frappe.db.sql(f"""
		select {si_select}
		from `tabSales Invoice Payment` sip
		inner join `tabSales Invoice` si on si.name = sip.parent
		where si.docstatus = 1 and sip.account = %(account)s {date_condition.format('sip.')}
	""", args)

	pi_value = frappe.db.sql(f"""
		select {pi_select}
		from `tabPurchase Invoice`
		where docstatus = 1 and cash_bank_account = %(account)s {date_condition.format('')}
		""", args)

	if value_type == "balance":
		jv_value = flt(jv_value[0][0]) if jv_value else 0.0
		pe_value = flt(pe_value[0][0]) if pe_value else 0.0
		si_value = flt(si_value[0][0]) if si_value else 0.0
		pi_value = flt(pi_value[0][0]) if pi_value else 0.0
		return jv_value + pe_value + si_value + pi_value
	elif value_type == "last_clearance_date":
		jv_value = jv_value[0][0] if jv_value else None
		pe_value = pe_value[0][0] if pe_value else None
		si_value = si_value[0][0] if si_value else None
		pi_value = pi_value[0][0] if pi_value else None

		values = [v for v in (jv_value, pe_value, si_value, pi_value) if v]
		if values:
			return max(values)
