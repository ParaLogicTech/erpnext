# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate
from erpnext.accounts.utils import get_balance_on
from erpnext.accounts.doctype.bank_reconciliation.bank_reconciliation import get_opening_balance


def execute(filters=None):
	filters = frappe._dict(filters)
	filters["to_date"] = getdate(filters["to_date"])
	filters["from_date"] = getdate(filters["from_date"])

	columns = get_columns()

	if not filters.get("bank_account"):
		return columns, []

	filters["account"] = frappe.db.get_value("Bank Account", filters.bank_account, "account")
	filters["suspense_account"] = frappe.db.get_value("Bank Account", filters.bank_account, "suspense_account")
	if not filters.get("account"):
		return columns, []

	account_currency = frappe.db.get_value("Account", filters.account, "account_currency")

	entries = get_entries(
		filters.suspense_account or filters.account,
		filters.from_date,
		filters.to_date,
		exclude_reconciliation_jv=filters.suspense_account,
	)

	uncleared_incoming = []
	uncleared_outgoing = []
	cleared_incoming = []
	cleared_outgoing = []
	total_uncleared_incoming, total_uncleared_outgoing, total_cleared_incoming, total_cleared_outgoing = 0, 0, 0, 0

	for d in entries:
		d.indent = 1

		is_cleared = d.get('clearance_date') and filters['from_date'] <= getdate(d.get('clearance_date')) <= filters['to_date']
		diff = d.debit - d.credit

		if diff > 0:
			if is_cleared:
				cleared_incoming.append(d)
				total_cleared_incoming += diff
			else:
				uncleared_incoming.append(d)
				total_uncleared_incoming += diff
		else:
			if is_cleared:
				cleared_outgoing.append(d)
				total_cleared_outgoing += diff
			else:
				uncleared_outgoing.append(d)
				total_uncleared_outgoing += diff

	opening_balance_statement = get_opening_balance(filters["bank_account"], filters["from_date"])
	closing_balance_statement = flt(opening_balance_statement) + flt(total_cleared_incoming) + flt(total_cleared_outgoing)

	closing_balance_ledger = get_balance_on(filters["account"], filters["to_date"])
	if filters.suspense_account:
		closing_balance_ledger += get_balance_on(filters["suspense_account"], filters["to_date"])

	data = [
		get_balance_row(
			_("'Bank Statement Opening Balance'"),
			opening_balance_statement,
			account_currency
		),
		{},

		get_balance_row(
			_("'Total Uncleared Incoming'"),
			total_uncleared_incoming,
			account_currency
		),
		*uncleared_incoming,
		{},

		get_balance_row(
			_("'Total Uncleared Outgoing'"),
			total_uncleared_outgoing,
			account_currency
		),
		*uncleared_outgoing,
		{},

		get_balance_row(
			_("'Total Cleared Incoming'"),
			total_cleared_incoming,
			account_currency,
			collapsed=True
		),
		*cleared_incoming,
		{},

		get_balance_row(
			_("'Total Cleared Outgoing'"),
			total_cleared_outgoing,
			account_currency,
			collapsed=True,
		),
		*cleared_outgoing,
		{},

		get_balance_row(
			_("'General Ledger Closing Balance'"),
			closing_balance_ledger,
			account_currency
		),
		get_balance_row(
			_("'Bank Statement Closing Balance'"),
			closing_balance_statement,
			account_currency
		)
	]

	return columns, data


def get_entries(account, from_date, to_date, exclude_reconciliation_jv=False):
	args = {
		"account": account,
		"from_date": from_date,
		"to_date": to_date,
	}

	exclude_reconciliation_jv_condition = ""
	if exclude_reconciliation_jv:
		exclude_reconciliation_jv_condition = "and jv.voucher_type != 'Bank Clearance Entry'"

	journal_entries = frappe.db.sql(f"""
		select
			'Journal Entry' as payment_document,
			jv.posting_date,
			jv.name as payment_entry,
			jvd.debit_in_account_currency as debit,
			jvd.credit_in_account_currency as credit,
			jvd.against_account,
			jv.cheque_no as reference_no,
			jv.cheque_date as ref_date,
			jvd.clearance_date,
			jvd.account_currency
		from `tabJournal Entry Account` jvd
		inner join `tabJournal Entry` jv on jv.name = jvd.parent
		where jv.docstatus = 1
			and jvd.account = %(account)s
			and jv.is_opening != 'Yes'
			and (
				jv.posting_date between %(from_date)s and %(to_date)s
				or jvd.clearance_date between %(from_date)s and %(to_date)s
			)
			{exclude_reconciliation_jv_condition}
	""", args, as_dict=1)

	payment_entries = frappe.db.sql("""
		select
			'Payment Entry' as payment_document,
			name as payment_entry,
			reference_no,
			reference_date as ref_date,
			if(paid_to = %(account)s, received_amount_after_tax, 0) as debit,
			if(paid_from = %(account)s, paid_amount_after_tax, 0) as credit,
			posting_date,
			if(ifnull(party_name, '') != '', party_name, if(paid_from = %(account)s, paid_to, paid_from)) as against_account,
			clearance_date,
			if(paid_to = %(account)s, paid_to_account_currency, paid_from_account_currency) as account_currency
		from `tabPayment Entry`
		where docstatus = 1
			and (paid_from = %(account)s or paid_to = %(account)s)
			and (
				posting_date between %(from_date)s and %(to_date)s
				or clearance_date between %(from_date)s and %(to_date)s
			)
	""", args, as_dict=1)

	pos_sales_invoices = frappe.db.sql("""
		select
			'Sales Invoice Payment' as payment_document,
			sip.name as payment_entry,
			sip.amount as debit,
			0 as credit,
			si.posting_date,
			si.bill_to_name as against_account,
			sip.clearance_date,
			account.account_currency
		from `tabSales Invoice Payment` sip
		inner join `tabSales Invoice` si on si.name = sip.parent
		inner join `tabAccount` account on account.name = sip.account
		where si.docstatus = 1
			and sip.account = %(account)s
			and (
				si.posting_date between %(from_date)s and %(to_date)s
				or sip.clearance_date between %(from_date)s and %(to_date)s
			)
	""", args, as_dict=1)

	paid_purchase_invoices = frappe.db.sql("""
		select
			'Purchase Invoice' as payment_document,
			pi.name as payment_entry,
			pi.paid_amount as credit,
			0 as debit,
			pi.posting_date,
			pi.supplier_name as against_account,
			pi.clearance_date,
			account.account_currency
		from `tabPurchase Invoice` pi
		inner join `tabAccount` account on account.name = pi.cash_bank_account
		where pi.docstatus = 1
			and pi.cash_bank_account = %(account)s
			and (
				pi.posting_date between %(from_date)s and %(to_date)s
				or pi.clearance_date between %(from_date)s and %(to_date)s
			)
	""", args, as_dict=1)

	return sorted(
		payment_entries + journal_entries + pos_sales_invoices + paid_purchase_invoices,
		key=lambda k: k['posting_date'] or getdate(nowdate())
	)


def get_balance_row(label, amount, account_currency, collapsed=False):
	if amount > 0:
		return {
			"payment_entry": label,
			"debit": amount,
			"credit": 0,
			"account_currency": account_currency,
			"_bold": 1,
			"_collapsed": collapsed
		}
	else:
		return {
			"payment_entry": label,
			"debit": 0,
			"credit": abs(amount),
			"account_currency": account_currency,
			"_bold": 1,
			"_collapsed": collapsed
		}


def get_columns():
	return [
		{
			"fieldname": "payment_entry",
			"label": _("Payment Entry"),
			"fieldtype": "Dynamic Link",
			"options": "payment_document",
			"width": 250
		},
		{
			"fieldname": "posting_date",
			"label": _("Posting Date"),
			"fieldtype": "Date",
			"width": 90
		},
		{
			"fieldname": "clearance_date",
			"label": _("Clearance Date"),
			"fieldtype": "Date",
			"width": 110
		},
		{
			"fieldname": "reference_no",
			"label": _("Reference"),
			"fieldtype": "Data",
			"width": 100
		},
		{
			"fieldname": "debit",
			"label": _("Debit"),
			"fieldtype": "Currency",
			"options": "account_currency",
			"width": 120
		},
		{
			"fieldname": "credit",
			"label": _("Credit"),
			"fieldtype": "Currency",
			"options": "account_currency",
			"width": 120
		},
		{
			"fieldname": "against_account",
			"label": _("Against Account"),
			"fieldtype": "Data",
			"width": 200
		},
		{
			"fieldname": "account_currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"width": 100
		}
	]
