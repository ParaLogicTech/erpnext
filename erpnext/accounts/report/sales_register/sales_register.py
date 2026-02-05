# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
import frappe
import erpnext
from frappe import _
from frappe.utils import flt
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
		row = frappe._dict({
			'invoice': inv.name,
			'posting_date': inv.posting_date,
			'customer': inv.bill_to,
			'customer_name': inv.bill_to_name,
		})

		if additional_query_columns:
			for col in additional_query_columns:
				row.update({
					col: inv.get(col)
				})

		row.update({
			'customer_group': inv.get("customer_group"),
			'territory': inv.get("territory"),
			'tax_id': inv.get("tax_id"),
			'receivable_account': inv.debit_to,
			'project': inv.project,
			'owner': inv.owner,
			'remarks': inv.remarks,
			'mode_of_payment': ", ".join(mode_of_payment_map.get(inv.name, [])),
			'sales_order': ", ".join(sales_order_map.get(inv.name, [])),
			'delivery_note': ", ".join(delivery_note_map.get(inv.name, [])),
			'cost_center': ", ".join(cost_center_map.get(inv.name, [])),
			'warehouse': ", ".join(warehouse_map.get(inv.name, [])),
			'currency': company_currency,
		})

		# map income values
		net_total = 0
		total_tax = 0
		for acc in income_accounts + asset_accounts + tax_accounts:
			credit_amount = flt(gl_map.get(inv.name, {}).get(acc))
			if credit_amount:
				account_has_amount.add(acc)

			if acc in income_accounts or acc in asset_accounts:
				net_total += credit_amount
			elif acc in tax_accounts:
				total_tax += credit_amount

			row[frappe.scrub(acc)] = credit_amount

		# total tax, grand total, outstanding amount and rounded total
		row.update({
			'net_total': inv.base_net_total or net_total,
			'tax_total': total_tax,
			'grand_total': inv.base_grand_total,
			'rounded_total': inv.base_rounded_total,
			'outstanding_amount': inv.outstanding_amount,
		})

		data.append(row)

	income_accounts = [acc for acc in income_accounts if acc in account_has_amount]
	asset_accounts = [acc for acc in asset_accounts if acc in account_has_amount]
	tax_accounts = [acc for acc in tax_accounts if acc in account_has_amount]

	columns = get_columns(income_accounts, asset_accounts, tax_accounts, additional_table_columns)

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


def get_columns(income_accounts, asset_accounts, tax_accounts, additional_table_columns):
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

	return columns


def get_invoices(filters, additional_query_columns):
	if additional_query_columns:
		additional_query_columns = ', ' + ', '.join(additional_query_columns)
	else:
		additional_query_columns = ""

	conditions = get_conditions(filters)
	return frappe.db.sql(f"""
		select
			inv.name, inv.posting_date, inv.debit_to, inv.project,
			inv.customer, inv.customer_name, inv.bill_to, inv.bill_to_name,
			inv.owner, inv.remarks, inv.territory, inv.tax_id, c.customer_group,
			inv.base_net_total, inv.base_grand_total, inv.base_rounded_total, inv.outstanding_amount
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
		conditions += " and posting_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " and posting_date <= %(to_date)s"

	if filters.get("owner"):
		conditions += " and owner = %(owner)s"

	if filters.get("mode_of_payment"):
		conditions += """ and exists(
			select name
			from `tabSales Invoice Payment`
			where parent = `tabSales Invoice`.name and `tabSales Invoice Payment`.mode_of_payment = %(mode_of_payment)s
		)"""

	if filters.get("cost_center"):
		conditions += """ and exists(
			select name
			from `tabSales Invoice Item`
			where parent = `tabSales Invoice`.name and `tabSales Invoice Item`.cost_center = %(cost_center)s
		)"""

	if filters.get("warehouse"):
		conditions += """ and exists(
			select name
			from `tabSales Invoice Item`
			where parent = `tabSales Invoice`.name and `tabSales Invoice Item`.warehouse = %(warehouse)s
		)"""

	if filters.get("brand"):
		conditions += """ and exists(
			select name
			from `tabSales Invoice Item`
			where parent = `tabSales Invoice`.name and `tabSales Invoice Item`.brand = %(brand)s
		)"""

	if filters.get("item_group"):
		conditions += """ and exists(
			select name
			from `tabSales Invoice Item`
			where parent = `tabSales Invoice`.name and `tabSales Invoice Item`.item_group = %(item_group)s
		)"""

	accounting_dimensions = get_accounting_dimensions(as_list=False)

	if accounting_dimensions:
		common_condition = """
			and exists(select name from `tabSales Invoice Item`
				where parent=`tabSales Invoice`.name
			"""
		for dimension in accounting_dimensions:
			if filters.get(dimension.fieldname) and dimension.fieldname not in ("customer_group", "item_group"):
				if frappe.get_cached_value('DocType', dimension.document_type, 'is_tree'):
					filters[dimension.fieldname] = get_dimension_with_children(dimension.document_type,
						filters.get(dimension.fieldname))

					conditions += common_condition + "and ifnull(`tabSales Invoice Item`.{0}, '') in %({0})s)".format(dimension.fieldname)
				else:
					conditions += common_condition + "and ifnull(`tabSales Invoice Item`.{0}, '') in (%({0})s))".format(dimension.fieldname)

	return conditions
