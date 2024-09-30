# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe, erpnext
from frappe import _
from frappe.model.meta import get_field_precision
from frappe.utils import flt, cint, get_datetime, format_datetime


class StockOverReturnError(frappe.ValidationError): pass


def validate_return(doc):
	if not doc.meta.get_field("is_return") or not doc.is_return:
		return

	if doc.return_against:
		validate_return_against(doc)
		validate_returned_items(doc)


def validate_return_against(doc):
	if not frappe.db.exists(doc.doctype, doc.return_against):
			frappe.throw(_("Invalid {0}: {1}")
				.format(doc.meta.get_label("return_against"), doc.return_against))
	else:
		ref_doc = frappe.get_doc(doc.doctype, doc.return_against)

		party_type = "customer" if doc.doctype in ("Sales Invoice", "Delivery Note") else "supplier"

		if ref_doc.company == doc.company and ref_doc.get(party_type) == doc.get(party_type) and ref_doc.docstatus == 1:
			# validate posting date time
			return_posting_datetime = "%s %s" % (doc.posting_date, doc.get("posting_time") or "00:00:00")
			ref_posting_datetime = "%s %s" % (ref_doc.posting_date, ref_doc.get("posting_time") or "00:00:00")

			if get_datetime(return_posting_datetime) < get_datetime(ref_posting_datetime):
				frappe.throw(_("Posting timestamp must be after {0}").format(format_datetime(ref_posting_datetime)))

			# validate same exchange rate
			if doc.conversion_rate != ref_doc.conversion_rate:
				frappe.throw(_("Exchange Rate must be same as {0} {1} ({2})")
					.format(doc.doctype, doc.return_against, ref_doc.conversion_rate))

		# validate same transaction type
		if doc.meta.get_field("transaction_type") and doc.transaction_type != ref_doc.transaction_type:
			frappe.throw(_("Transaction Type must be the same as {0} {1} ({2})")
				.format(doc.doctype, doc.return_against, ref_doc.transaction_type))


def validate_returned_items(doc):
	from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos

	valid_items = frappe._dict()

	select_fields = "item_code, qty, stock_qty, rate, parenttype, conversion_factor"
	if doc.doctype != 'Purchase Invoice':
		select_fields += ",serial_no, batch_no"

	if doc.doctype in ['Purchase Invoice', 'Purchase Receipt']:
		select_fields += ",rejected_qty, received_qty"

	previous_dt = None
	previous_doc_fields = ""
	previous_docs = []
	previous_doc_item_codes = []
	if doc.doctype == 'Sales Invoice':
		previous_dt = "Delivery Note"
		previous_doc_fields = ",delivery_note"
	if doc.doctype == 'Purchase Invoice':
		previous_dt = "Purchase Receipt"
		previous_doc_fields = ",purchase_receipt"

	return_against_items = frappe.db.sql("""select {0}{1} from `tab{2} Item` where parent = %s"""
		.format(select_fields, previous_doc_fields, doc.doctype), doc.return_against, as_dict=1)
	for d in return_against_items:
		if previous_dt == 'Delivery Note' and d.delivery_note:
			previous_docs.append(d.delivery_note)
			previous_doc_item_codes.append(d.item_code)
		elif previous_dt == 'Purchase Receipt' and d.purchase_receipt:
			previous_docs.append(d.purchase_receipt)
			previous_doc_item_codes.append(d.item_code)
		else:
			valid_items = get_ref_item_dict(valid_items, d)

	if previous_dt and previous_docs:
		previous_docs = list(set(previous_docs))
		previous_doc_item_codes = list(set(previous_doc_item_codes))
		for previous_dn in previous_docs:
			previous_doc_items = frappe.db.sql("""select {0} from `tab{1} Item` where parent = %s and item_code in ({2})"""
				.format(select_fields, previous_dt, ", ".join(['%s']*len(previous_doc_item_codes))), [previous_dn] + previous_doc_item_codes, as_dict=1)
			for d in previous_doc_items:
				valid_items = get_ref_item_dict(valid_items, d)

	if doc.doctype in ("Delivery Note", "Sales Invoice"):
		for d in frappe.db.sql("""select item_code, qty, serial_no, batch_no from `tabPacked Item`
			where parent = %s""".format(doc.doctype), doc.return_against, as_dict=1):
				valid_items = get_ref_item_dict(valid_items, d)

	already_returned_items = get_already_returned_items(doc)

	# ( not mandatory when it is Purchase Invoice or a Sales Invoice without Update Stock )
	warehouse_mandatory = not ((doc.doctype=="Purchase Invoice" or doc.doctype=="Sales Invoice") and not doc.update_stock)

	items_returned = False
	for d in doc.get("items"):
		if flt(d.qty) > 0 or flt(d.get('received_qty')) > 0:
			frappe.throw(_("Row #{0}: Item Qty must be negative for return").format(d.idx))

		if d.item_code:
			if d.item_code not in valid_items:
				frappe.throw(_("Row #{0}: Returned Item {1} does not exist in {2} {3}")
					.format(d.idx, d.item_code, doc.doctype, doc.return_against))
			else:
				return_against_row_name_field = None
				if doc.doctype == "Purchase Receipt":
					return_against_row_name_field = "purchase_receipt_item"
				elif doc.doctype == "Purchase Invoice":
					return_against_row_name_field = "purchase_invoice_item"
				elif doc.doctype == "Delivery Note":
					return_against_row_name_field = "delivery_note_item"
				elif doc.doctype == "Sales Invoice":
					return_against_row_name_field = "sales_invoice_item"

				if return_against_row_name_field and not d.get(return_against_row_name_field):
					frappe.throw(_("Row # {0}: Returned Item {1} does not have reference to returned against {2} Item")
						.format(d.idx, d.item_code, doc.doctype))

				ref = valid_items.get(d.item_code, frappe._dict())
				validate_quantity(doc, d, ref, valid_items, already_returned_items)

				'''if ref.rate and doc.doctype in ("Delivery Note", "Sales Invoice") and flt(d.rate) > ref.rate:
					frappe.throw(_("Row # {0}: Rate cannot be greater than the rate used in {1} {2}")
						.format(d.idx, doc.doctype, doc.return_against))'''

				if ref.batch_no and d.batch_no not in ref.batch_no:
					frappe.throw(_("Row # {0}: Batch No must be same as {1} {2}")
						.format(d.idx, doc.doctype, doc.return_against))

				if ref.serial_no:
					if not d.serial_no:
						frappe.throw(_("Row # {0}: Serial No is mandatory").format(d.idx))
					else:
						serial_nos = get_serial_nos(d.serial_no)
						for s in serial_nos:
							if s not in ref.serial_no:
								frappe.throw(_("Row # {0}: Serial No {1} does not match with {2} {3}")
									.format(d.idx, s, doc.doctype, doc.return_against))

				if warehouse_mandatory and frappe.db.get_value("Item", d.item_code, "is_stock_item") \
					and not d.get("warehouse"):
						frappe.throw(_("Warehouse is mandatory"))

			items_returned = True

		elif d.item_name:
			items_returned = True

	if not items_returned:
		frappe.throw(_("Atleast one item should be entered with negative quantity in return document"))


def validate_quantity(doc, args, ref, valid_items, already_returned_items):
	fields = ['stock_qty']
	if doc.doctype in ['Purchase Receipt', 'Purchase Invoice']:
		fields.extend(['received_qty', 'rejected_qty'])

	already_returned_data = already_returned_items.get(args.item_code) or {}

	company_currency = erpnext.get_company_currency(doc.company)
	stock_qty_precision = get_field_precision(frappe.get_meta(doc.doctype + " Item")
			.get_field("stock_qty"), company_currency)

	for column in fields:
		returned_qty = flt(already_returned_data.get(column, 0)) if len(already_returned_data) > 0 else 0

		if column == 'stock_qty':
			reference_qty = ref.get(column)
			current_stock_qty = args.get(column)
		else:
			reference_qty = ref.get(column) * ref.get("conversion_factor", 1.0)
			current_stock_qty = args.get(column) * args.get("conversion_factor", 1.0)

		max_returnable_qty = flt(reference_qty, stock_qty_precision) - returned_qty
		label = column.replace('_', ' ').title()

		if reference_qty:
			if flt(args.get(column)) > 0:
				frappe.throw(_("{0} must be negative in return document").format(label))
			elif returned_qty >= reference_qty and args.get(column):
				frappe.throw(_("Item {0} has already been returned")
					.format(args.item_code), StockOverReturnError)
			elif abs(flt(current_stock_qty, stock_qty_precision)) > max_returnable_qty:
				frappe.throw(_("Row # {0}: Cannot return more than {1} for Item {2}")
					.format(args.idx, max_returnable_qty, args.item_code), StockOverReturnError)


def get_ref_item_dict(valid_items, ref_item_row):
	from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos

	valid_items.setdefault(ref_item_row.item_code, frappe._dict({
		"qty": 0,
		"rate": 0,
		"stock_qty": 0,
		"rejected_qty": 0,
		"received_qty": 0,
		"serial_no": [],
		"conversion_factor": ref_item_row.get("conversion_factor", 1),
		"batch_no": []
	}))
	item_dict = valid_items[ref_item_row.item_code]
	item_dict["qty"] += ref_item_row.qty
	item_dict["stock_qty"] += ref_item_row.get('stock_qty', 0)
	if ref_item_row.get("rate", 0) > item_dict["rate"]:
		item_dict["rate"] = ref_item_row.get("rate", 0)

	if ref_item_row.parenttype in ['Purchase Invoice', 'Purchase Receipt']:
		item_dict["received_qty"] += ref_item_row.received_qty
		item_dict["rejected_qty"] += ref_item_row.rejected_qty

	if ref_item_row.get("serial_no"):
		item_dict["serial_no"] += get_serial_nos(ref_item_row.serial_no)

	if ref_item_row.get("batch_no"):
		item_dict["batch_no"].append(ref_item_row.batch_no)

	return valid_items


def get_already_returned_items(doc):
	fields = ['qty', 'stock_qty', 'received_qty', 'rejected_qty']
	column = 'child.item_code, sum(abs(child.qty)) as qty, sum(abs(child.stock_qty)) as stock_qty'
	if doc.doctype in ['Purchase Invoice', 'Purchase Receipt']:
		column += """, sum(abs(child.rejected_qty) * child.conversion_factor) as rejected_qty,
			sum(abs(child.received_qty) * child.conversion_factor) as received_qty"""

	data = frappe.db.sql("""
		select {0}
		from
			`tab{1} Item` child, `tab{2}` par
		where
			child.parent = par.name and par.docstatus = 1
			and par.is_return = 1 and par.return_against = %s
		group by item_code
	""".format(column, doc.doctype, doc.doctype), doc.return_against, as_dict=1)

	# Check previous or future document for returns
	others_docs = None
	if doc.doctype == 'Sales Invoice':
		other_dt = 'Delivery Note'
		others_docs = list(set([d.delivery_note for d in doc.items if d.delivery_note]))
		other_dt_condition = 'and par.return_against in ({0})'.format(", ".join(['%s'] * len(others_docs)))
	elif doc.doctype == 'Purchase Invoice':
		other_dt = 'Purchase Receipt'
		others_docs = list(set([d.purchase_receipt for d in doc.items if d.purchase_receipt]))
		other_dt_condition = 'and par.return_against in ({0})'.format(", ".join(['%s'] * len(others_docs)))
	elif doc.doctype == 'Delivery Note':
		other_dt = 'Sales Invoice'
		others_docs = [doc.return_against]
		other_dt_condition = 'and child.delivery_note = %s and par.update_stock = 1'
	elif doc.doctype == 'Purchase Receipt':
		other_dt = 'Purchase Invoice'
		others_docs = [doc.return_against]
		other_dt_condition = 'and child.purchase_receipt = %s and par.update_stock = 1'

	other_dt_data = []
	if others_docs:
		other_dt_data = frappe.db.sql("""
			select {0}
			from
				`tab{1} Item` child, `tab{1}` par
			where
				child.parent = par.name and par.docstatus = 1
				and par.is_return = 1 and ifnull(par.return_against, '') != ''
				{2}
			group by item_code
		""".format(column, other_dt, other_dt_condition), others_docs, as_dict=1)

	items = {}

	for d in data + other_dt_data:
		if d.item_code not in items:
			items[d.item_code] = frappe._dict()
			for f in fields:
				items[d.item_code][f] = 0

		for f in fields:
			items[d.item_code][f] += flt(d.get(f))

	return items


def make_return_doc(doctype, source_name, target_doc=None):
	from frappe.model.mapper import get_mapped_doc

	def set_missing_values(source, target):
		doc = frappe.get_doc(target)

		# Return Fields
		doc.ignore_pricing_rule = 1
		doc.is_return = 1
		doc.return_against = source.name

		# Default Return Warehouse
		default_warehouse_for_sales_return = frappe.get_cached_value("Company", source.company,
			"default_warehouse_for_sales_return")
		doc.set_warehouse = default_warehouse_for_sales_return or source.set_warehouse

		# Return Options
		if frappe.flags.args:
			if doctype in ('Sales Invoice', 'Purchase Invoice') and frappe.flags.args.update_stock:
				doc.update_stock = cint(frappe.flags.args.update_stock == "Yes")
			if frappe.flags.args.reopen_order:
				doc.reopen_order = cint(frappe.flags.args.reopen_order == "Yes")

		if doctype == "Sales Invoice":
			doc.is_pos = source.is_pos

			# look for Print Heading "Credit Note"
			if not doc.select_print_heading:
				doc.select_print_heading = frappe.db.get_value("Print Heading", _("Credit Note"))

		elif doctype == "Purchase Invoice":
			# look for Print Heading "Debit Note"
			doc.select_print_heading = frappe.db.get_value("Print Heading", _("Debit Note"))

		for tax in doc.get("taxes"):
			if tax.charge_type == "Actual":
				tax.tax_amount = -1 * tax.tax_amount

		if doc.get("is_return"):
			if doc.doctype == 'Sales Invoice':
				doc.set('payments', [])

				change_adjusted = False
				for data in source.payments:
					paid_amount = data.amount
					if data.type == "Cash" and not change_adjusted:
						paid_amount -= flt(source.change_amount)
						change_adjusted = True

					doc.append('payments', {
						'mode_of_payment': data.mode_of_payment,
						'type': data.type,
						'amount': -1 * paid_amount,
					})
			elif doc.doctype == 'Purchase Invoice':
				doc.paid_amount = -1 * source.paid_amount
				doc.base_paid_amount = -1 * source.base_paid_amount
				doc.payment_terms_template = ''
				doc.payment_schedule = []

		if doc.get("is_return") and hasattr(doc, "packed_items"):
			for d in doc.get("packed_items"):
				d.qty = d.qty * -1

		doc.discount_amount = -1 * source.discount_amount
		doc.run_method("calculate_taxes_and_totals")

	def update_item(source_doc, target_doc, source_parent, target_parent):
		default_warehouse_for_sales_return = frappe.get_cached_value("Company", source_parent.company,
			"default_warehouse_for_sales_return")

		target_doc.qty = -1 * source_doc.qty

		if doctype == "Purchase Receipt":
			target_doc.qty = -1 * flt(source_doc.qty - source_doc.billed_qty - source_doc.returned_qty,
				target_doc.precision('qty'))
			target_doc.received_qty = target_doc.qty if target_doc.qty else -1 * source_doc.rejected_qty
			target_doc.rejected_qty = -1 * source_doc.rejected_qty
			target_doc.stock_qty = -1 * source_doc.stock_qty
			target_doc.purchase_order = source_doc.purchase_order
			target_doc.purchase_receipt_item = source_doc.name
			target_doc.purchase_order_item = source_doc.purchase_order_item
			target_doc.delivery_note_item = source_doc.delivery_note_item
			target_doc.rejected_warehouse = source_doc.rejected_warehouse

		elif doctype == "Purchase Invoice":
			target_doc.qty = -1 * source_doc.qty
			target_doc.received_qty = -1 * source_doc.received_qty
			target_doc.rejected_qty = -1 * source_doc.rejected_qty
			target_doc.stock_qty = -1 * source_doc.stock_qty
			target_doc.purchase_order = source_doc.purchase_order
			target_doc.purchase_receipt = source_doc.purchase_receipt
			target_doc.rejected_warehouse = source_doc.rejected_warehouse
			target_doc.purchase_order_item = source_doc.purchase_order_item
			target_doc.purchase_receipt_item = source_doc.purchase_receipt_item
			target_doc.purchase_invoice_item = source_doc.name
			target_doc.sales_invoice_item = source_doc.sales_invoice_item

		elif doctype == "Delivery Note":
			if frappe.get_cached_value("Stock Settings", None, "allow_delivery_returns_after_billing"):
				target_doc.qty = -1 * flt(source_doc.qty - source_doc.returned_qty)
			else:
				target_doc.qty = -1 * flt(source_doc.qty - source_doc.billed_qty - source_doc.returned_qty)
			target_doc.qty = flt(target_doc.qty, target_doc.precision("qty"))

			target_doc.delivery_note_item = source_doc.name
			target_doc.sales_order = source_doc.sales_order
			target_doc.sales_order_item = source_doc.sales_order_item
			target_doc.sales_invoice = source_doc.sales_invoice
			target_doc.sales_invoice_item = source_doc.sales_invoice_item
			target_doc.packing_slip = source_doc.packing_slip
			target_doc.packing_slip_item = source_doc.packing_slip_item

			target_doc.target_warehouse = source_doc.target_warehouse
			target_doc.expense_account = source_doc.expense_account
			if default_warehouse_for_sales_return:
				target_doc.warehouse = default_warehouse_for_sales_return

		elif doctype == "Sales Invoice":
			target_doc.sales_invoice_item = source_doc.name
			target_doc.sales_order = source_doc.sales_order
			target_doc.sales_order_item = source_doc.sales_order_item
			target_doc.delivery_note = source_doc.delivery_note
			target_doc.delivery_note_item = source_doc.delivery_note_item
			target_doc.packing_slip = source_doc.packing_slip
			target_doc.packing_slip_item = source_doc.packing_slip_item

			target_doc.target_warehouse = source_doc.target_warehouse
			target_doc.expense_account = source_doc.expense_account
			if default_warehouse_for_sales_return:
				target_doc.warehouse = default_warehouse_for_sales_return

	def update_terms(source_doc, target_doc, source_parent, target_parent):
		target_doc.payment_amount = -source_doc.payment_amount

	mapper = {
		doctype: {
			"doctype": doctype,
			"validation": {
				"docstatus": ["=", 1],
			},
			"field_map": {
				"to_warehouse": "to_warehouse",
				"supplier_warehouse": "supplier_warehouse",
				"po_no": "po_no",
				"po_date": "po_date",
			},
			"field_no_map": ["is_subcontracted"],
		},
		doctype + " Item": {
			"doctype": doctype + " Item",
			"field_map": {
				"serial_no": "serial_no",
				"batch_no": "batch_no",
				"vehicle": "vehicle"
			},
			"postprocess": update_item
		},
		"Payment Schedule": {
			"doctype": "Payment Schedule",
			"postprocess": update_terms
		}
	}

	frappe.utils.call_hook_method("update_sales_purchase_return_mapper", mapper, doctype)

	doclist = get_mapped_doc(doctype, source_name,	mapper, target_doc, set_missing_values)

	return doclist
