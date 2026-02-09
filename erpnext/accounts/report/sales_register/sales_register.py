# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
import erpnext
from frappe import _
from frappe.utils import flt
from erpnext.accounts.report.financial_statements import get_cost_centers_with_children
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children,
)


def execute(filters=None):
	return _execute(filters)


def _execute(filters, additional_table_columns=None, additional_query_columns=None):
	filters = frappe._dict(filters or {})

	company_currency = erpnext.get_company_currency(filters.get("company"))

	invoice_list = get_invoices(filters, additional_query_columns)

	(
		income_accounts,
		asset_accounts,
		tax_accounts,
		gl_map,
		cost_center_map,
		mode_of_payment_map,
		warehouse_map,
		sales_order_map,
		delivery_note_map,
	) = get_invoice_accounts_data(invoice_list)

	if not invoice_list:
		return [], invoice_list

	data = []
	account_has_amount = set()

	for inv in invoice_list:
		row = frappe._dict()

		if additional_query_columns:
			for col in additional_query_columns:
				row.update({
					col: inv.get(col)
				})

		if inv.get("branch"):
			filters["has_branch"] = True

		row.update({
			'invoice': inv.name,
			'posting_date': inv.posting_date,
			'customer': inv.bill_to,
			'customer_name': inv.bill_to_name,
			'customer_group': inv.get("customer_group"),
			'company': inv.get("company"),
			'branch': inv.get("branch"),
			'territory': inv.get("territory"),
			'tax_id': inv.get("tax_id"),
			'receivable_account': inv.debit_to,
			'project': inv.project,
			'owner': inv.owner,
			'remarks': inv.remarks,
			'mode_of_payment': ", ".join(mode_of_payment_map.get(inv.name, [])),
			'sales_order': ", ".join(sales_order_map.get(inv.name, [])),
			'delivery_note': ", ".join(delivery_note_map.get(inv.name, [])),
			'cost_center': ", ".join(cost_center_map.get(inv.name, [])) or inv.cost_center,
			'warehouse': ", ".join(warehouse_map.get(inv.name, [])),
			'currency': company_currency,
		})

		# map income values
		for acc in income_accounts + asset_accounts + tax_accounts:
			credit_amount = flt(gl_map.get(inv.name, {}).get(acc))
			if credit_amount:
				account_has_amount.add(acc)

			row[frappe.scrub(acc)] = credit_amount

		# total tax, grand total, outstanding amount and rounded total
		row.update({
			'net_total': inv.base_net_total,
			'tax_total': inv.base_total_taxes_and_charges,
			'grand_total': inv.base_grand_total,
			'rounded_total': inv.base_rounded_total,
			'outstanding_amount': inv.outstanding_amount,
		})

		data.append(row)

	income_accounts = [acc for acc in income_accounts if acc in account_has_amount]
	asset_accounts = [acc for acc in asset_accounts if acc in account_has_amount]
	tax_accounts = [acc for acc in tax_accounts if acc in account_has_amount]

	columns = get_columns(income_accounts, asset_accounts, tax_accounts, additional_table_columns, filters)

	return columns, data


def get_invoice_accounts_data(invoice_list):
	income_accounts = set()
	asset_accounts = set()
	tax_accounts = []
	gl_map = {}
	cost_center_map = {}
	mode_of_payment_map = {}
	warehouse_map = {}
	sales_order_map = {}
	delivery_note_map = {}

	if invoice_list:
		invoice_names = [inv.name for inv in invoice_list]

		gl_data = frappe.db.sql("""
			select gle.voucher_no, gle.account, sum(gle.credit - gle.debit) as amount, gle.cost_center, acc.account_type
			from `tabGL Entry` gle
			inner join `tabAccount` acc on acc.name = gle.account
			where gle.voucher_type = 'Sales Invoice' and gle.voucher_no in %s
			group by voucher_no, account
		""", [invoice_names], as_dict=1)

		line_item_data = frappe.db.sql("""
			select income_account, discount_account, deferred_revenue_account,
				warehouse, is_stock_item, parent,
				sales_order, delivery_note
			from `tabSales Invoice Item`
			where parent in %s
		""", [invoice_names], as_dict=1)

		tax_accounts = frappe.db.sql_list("""
			select distinct account_head
			from `tabSales Taxes and Charges`
			where parenttype = 'Sales Invoice' and parent in %s and base_tax_amount_after_discount_amount != 0
		""", [invoice_names])

		mop_data = frappe.db.sql("""
			select distinct parent, mode_of_payment
			from `tabSales Invoice Payment`
			where parent in %s and amount != 0
		""", [invoice_names], as_dict=1)

		for d in line_item_data:
			if d.income_account:
				income_accounts.add(d.income_account)
			if d.discount_account:
				income_accounts.add(d.discount_account)
			if d.deferred_revenue_account:
				income_accounts.add(d.deferred_revenue_account)

			if d.sales_order:
				sales_order_map.setdefault(d.parent, set()).add(d.sales_order)
			if d.delivery_note:
				delivery_note_map.setdefault(d.parent, set()).add(d.delivery_note)
			if d.warehouse and d.is_stock_item:
				warehouse_map.setdefault(d.parent, set()).add(d.warehouse)

		for d in gl_data:
			gl_map.setdefault(d.voucher_no, {}).setdefault(d.account, 0)
			gl_map[d.voucher_no][d.account] += flt(d.amount)

			if d.account_type in ("Fixed Asset", "Accumulated Depreciation"):
				asset_accounts.add(d.account)

			if d.cost_center:
				cost_center_map.setdefault(d.voucher_no, set()).add(d.cost_center)

		for d in mop_data:
			if d.mode_of_payment:
				mode_of_payment_map.setdefault(d.parent, set()).add(d.mode_of_payment)

	income_accounts = sorted(list(income_accounts))
	asset_accounts = sorted(list(asset_accounts))
	tax_accounts = sorted(tax_accounts)

	return (
		income_accounts,
		asset_accounts,
		tax_accounts,
		gl_map,
		cost_center_map,
		mode_of_payment_map,
		warehouse_map,
		sales_order_map,
		delivery_note_map,
	)


def get_columns(income_accounts, asset_accounts, tax_accounts, additional_table_columns, filters):
	columns = [
		{
			'label': _("Invoice"),
			'fieldname': 'invoice',
			'fieldtype': 'Link',
			'options': 'Sales Invoice',
			'width': 120
		},
		{
			'label': _("Posting Date"),
			'fieldname': 'posting_date',
			'fieldtype': 'Date',
			'width': 80
		},
		{
			'label': _("Customer"),
			'fieldname': 'customer',
			'fieldtype': 'Link',
			'options': 'Customer',
			'width': 100
		},
		{
			'label': _("Customer Name"),
			'fieldname': 'customer_name',
			'fieldtype': 'Data',
			'width': 150
		},
	]

	if additional_table_columns:
		columns += additional_table_columns

	columns += [
		{
			'label': _("Branch"),
			'fieldname': 'branch',
			'fieldtype': 'Link',
			'options': 'Branch',
			'width': 100
		},
		{
			'label': _("Cost Center"),
			'fieldname': 'cost_center',
			'fieldtype': 'Link',
			'options': 'Cost Center',
			'width': 100
		},
		{
			'label': _("Project"),
			'fieldname': 'project',
			'fieldtype': 'Link',
			'options': 'Project',
			'width': 100
		},
		{
			'label': _("Owner"),
			'fieldname': 'owner',
			'fieldtype': 'Data',
			'width': 150
		},
		{
			'label': _("Remarks"),
			'fieldname': 'remarks',
			'fieldtype': 'Data',
			'width': 150
		},
	]

	for account in income_accounts:
		columns.append({
			"label": account,
			"fieldname": frappe.scrub(account),
			"fieldtype": "Currency",
			"options": 'currency',
			"width": 120
		})

	for account in asset_accounts:
		if account not in income_accounts:
			columns.append({
				"label": account,
				"fieldname": frappe.scrub(account),
				"fieldtype": "Currency",
				"options": 'currency',
				"width": 120
			})

	columns += [{
		"label": _("Net Total"),
		"fieldname": "net_total",
		"fieldtype": "Currency",
		"options": 'currency',
		"width": 120,
	}]

	for account in tax_accounts:
		if account not in income_accounts and account not in asset_accounts:
			columns.append({
				"label": account,
				"fieldname": frappe.scrub(account),
				"fieldtype": "Currency",
				"options": 'currency',
				"width": 120
			})

	columns += [
		{
			"label": _("Tax Total"),
			"fieldname": "tax_total",
			"fieldtype": "Currency",
			"options": 'currency',
			"width": 120
		},
		{
			"label": _("Grand Total"),
			"fieldname": "grand_total",
			"fieldtype": "Currency",
			"options": 'currency',
			"width": 120
		},
		{
			"label": _("Rounded Total"),
			"fieldname": "rounded_total",
			"fieldtype": "Currency",
			"options": 'currency',
			"width": 120
		},
		{
			"label": _("Outstanding Amount"),
			"fieldname": "outstanding_amount",
			"fieldtype": "Currency",
			"options": 'currency',
			"width": 120
		},
		{
			'label': _("Sales Order"),
			'fieldname': 'sales_order',
			'fieldtype': 'Link',
			'options': 'Sales Order',
			'width': 100
		},
		{
			'label': _("Delivery Note"),
			'fieldname': 'delivery_note',
			'fieldtype': 'Link',
			'options': 'Delivery Note',
			'width': 100
		},
		{
			'label': _("Warehouse"),
			'fieldname': 'warehouse',
			'fieldtype': 'Link',
			'options': 'Warehouse',
			'width': 100
		},
		{
			'label': _("Mode of Payment"),
			'fieldname': 'mode_of_payment',
			'fieldtype': 'Data',
			'width': 120
		},
		{
			'label': _("Receivable Account"),
			'fieldname': 'receivable_account',
			'fieldtype': 'Link',
			'options': 'Account',
			'width': 130
		},
		{
			'label': _("Tax Id"),
			'fieldname': 'tax_id',
			'fieldtype': 'Data',
			'width': 120
		},
		{
			'label': _("Customer Group"),
			'fieldname': 'customer_group',
			'fieldtype': 'Link',
			'options': 'Customer Group',
			'width': 120
		},
		{
			'label': _("Territory"),
			'fieldname': 'territory',
			'fieldtype': 'Link',
			'options': 'Territory',
			'width': 80
		},
	]

	if not filters.get("has_branch"):
		columns = [c for c in columns if c.get("fieldname") != "branch"]

	return columns


def get_invoices(filters, additional_query_columns):
	if additional_query_columns:
		additional_query_columns = ', ' + ', '.join(additional_query_columns)
	else:
		additional_query_columns = ""

	conditions = get_conditions(filters)
	return frappe.db.sql(f"""
		select
			inv.name, inv.posting_date,
			inv.company, inv.cost_center, inv.branch, inv.project,
			inv.customer, inv.customer_name, inv.bill_to, inv.bill_to_name,
			c.customer_group, inv.territory, inv.tax_id,
			inv.debit_to, inv.owner, inv.remarks,
			inv.base_net_total, inv.base_total_taxes_and_charges,
			inv.base_grand_total, inv.base_rounded_total, inv.outstanding_amount
			{additional_query_columns}
		from `tabSales Invoice` inv
		left join `tabCustomer` c on c.name = inv.bill_to
		where inv.docstatus = 1 {conditions}
		order by inv.posting_date desc, inv.creation desc
	""", filters, as_dict=1)


def get_conditions(filters):
	conditions = ""

	if filters.get("company"):
		conditions += " and inv.company = %(company)s"

	if filters.get("customer"):
		conditions += " and inv.bill_to = %(customer)s"

	if filters.get("customer_group"):
		lft, rgt = frappe.db.get_value("Customer Group", filters.get("customer_group"), ["lft", "rgt"])
		conditions += """ and c.customer_group in (
			select name from `tabCustomer Group` where lft >= {0} and rgt <= {1}
		)""".format(lft, rgt)

	if filters.get("from_date"):
		conditions += " and inv.posting_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " and inv.posting_date <= %(to_date)s"

	if filters.get("owner"):
		conditions += " and inv.owner = %(owner)s"

	if filters.get("cost_center"):
		filters.cost_center = get_cost_centers_with_children(filters.get("cost_center"))
		conditions += " and inv.cost_center in %(cost_center)s"

	accounting_dimensions = get_accounting_dimensions(as_list=False)
	for dimension in accounting_dimensions:
		if filters.get(dimension.fieldname):
			if frappe.get_cached_value('DocType', dimension.document_type, 'is_tree'):
				filters[dimension.fieldname] = get_dimension_with_children(dimension.document_type, filters.get(dimension.fieldname))
				conditions += " and inv.{0} in %({0})s".format(dimension.fieldname)
			else:
				conditions += " and inv.{0} = %({0})s".format(dimension.fieldname)

	return conditions
