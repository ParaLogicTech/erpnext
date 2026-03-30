# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from erpnext.selling.doctype.customer.customer import get_credit_limit

def execute(filters=None):
	if not filters: filters = {}
	#Check if customer id is according to naming series or customer name
	customer_naming_type = frappe.db.get_value("Selling Settings", None, "cust_master_name")
	columns = get_columns(customer_naming_type)

	data = []

	customer_list = get_details(filters)

	for d in customer_list:
		row = []

		outstanding_based_on_gle,  outstanding_based_on_so,  outstanding_based_on_dn = get_customer_outstanding(d.name, filters.get("company"),
			ignore_outstanding_sales_order=d.bypass_credit_limit_check)
		
		total_outstanding_amount = outstanding_based_on_gle+outstanding_based_on_so+outstanding_based_on_dn

		credit_limit = get_credit_limit(d.name, filters.get("company"))

		bal = flt(credit_limit) - flt(total_outstanding_amount)

		if customer_naming_type == "Naming Series":
			row = [
				d.name, d.customer_name, credit_limit, 
				outstanding_based_on_gle, outstanding_based_on_so, 
				outstanding_based_on_dn,  total_outstanding_amount, bal,
				d.bypass_credit_limit_check, d.is_frozen,
          d.disabled]
		else:
			row = [d.name, credit_limit, outstanding_based_on_gle, outstanding_based_on_so, 
				outstanding_based_on_dn,  total_outstanding_amount, bal,
          d.bypass_credit_limit_check, d.is_frozen, d.disabled]

		if credit_limit:
			data.append(row)

	return columns, data

def get_columns(customer_naming_type):
	columns = [
		_("Customer") + ":Link/Customer:120",
		_("Credit Limit") + ":Currency:120",
		_("General Ledger Outstanding Amt") + ":Currency:100",
		_("Sales Order Outstanding Amt") + ":Currency:100",
		_("Delivery Note Outstanding Amt") + ":Currency:100",
		_("Total Outstanding Amt") + ":Currency:100",
		_("Credit Balance") + ":Currency:120",
		_("Bypass credit check at Sales Order ") + ":Check:80",
		_("Is Frozen") + ":Check:80",
		_("Disabled") + ":Check:80",
	]

	if customer_naming_type == "Naming Series":
		columns.insert(1, _("Customer Name") + ":Data:120")

	return columns

def get_details(filters):
	conditions = ""

	if filters.get("customer"):
		conditions += " AND c.name = '" + filters.get("customer") + "'"

	return frappe.db.sql("""SELECT
			c.name, c.customer_name,
			ccl.bypass_credit_limit_check,
			c.is_frozen, c.disabled
		FROM `tabCustomer` c, `tabCustomer Credit Limit` ccl
		WHERE
			c.name = ccl.parent
			AND ccl.company = '{0}'
			{1}
	""".format( filters.get("company"),conditions), as_dict=1) #nosec

def get_customer_outstanding(customer, company, ignore_outstanding_sales_order=False, cost_center=None):
	# Outstanding based on GL Entries

	cond = ""
	if cost_center:
		lft, rgt = frappe.get_cached_value("Cost Center",
			cost_center, ['lft', 'rgt'])

		cond = """ and cost_center in (select name from `tabCost Center` where
			lft >= {0} and rgt <= {1})""".format(lft, rgt)

	outstanding_based_on_gle = frappe.db.sql("""
		select sum(debit) - sum(credit)
		from `tabGL Entry` where party_type = 'Customer'
		and party = %s and company=%s {0}""".format(cond), (customer, company))

	outstanding_based_on_gle = flt(outstanding_based_on_gle[0][0]) if outstanding_based_on_gle else 0

	# Outstanding based on Sales Order
	outstanding_based_on_so = 0.0

	# if credit limit check is bypassed at sales order level,
	# we should not consider outstanding Sales Orders, when customer credit balance report is run
	if not ignore_outstanding_sales_order:
		outstanding_based_on_so = frappe.db.sql("""
			select sum(base_grand_total*(100 - per_completed)/100)
			from `tabSales Order`
			where customer=%s and docstatus = 1 and company=%s
			and billing_status = 'To Bill' and status != 'Closed'""", (customer, company))

		outstanding_based_on_so = flt(outstanding_based_on_so[0][0]) if outstanding_based_on_so else 0.0

	# Outstanding based on Delivery Note, which are not created against Sales Order
	unmarked_delivery_note_items = frappe.db.sql("""select
			dn_item.name, dn_item.amount, dn.base_net_total, dn.base_grand_total
		from `tabDelivery Note` dn, `tabDelivery Note Item` dn_item
		where
			dn.name = dn_item.parent
			and dn.customer=%s and dn.company=%s
			and dn.docstatus = 1 and dn.status not in ('Closed', 'Stopped')
			and ifnull(dn_item.sales_order, '') = ''
			and ifnull(dn_item.sales_invoice, '') = ''
		""", (customer, company), as_dict=True)

	outstanding_based_on_dn = 0.0

	for dn_item in unmarked_delivery_note_items:
		si_amount = frappe.db.sql("""select sum(amount)
			from `tabSales Invoice Item`
			where delivery_note_item = %s and docstatus = 1""", dn_item.name)[0][0]

		if flt(dn_item.amount) > flt(si_amount) and dn_item.base_net_total:
			outstanding_based_on_dn += ((flt(dn_item.amount) - flt(si_amount)) \
				/ dn_item.base_net_total) * dn_item.base_grand_total

	return outstanding_based_on_gle,  outstanding_based_on_so,  outstanding_based_on_dn
