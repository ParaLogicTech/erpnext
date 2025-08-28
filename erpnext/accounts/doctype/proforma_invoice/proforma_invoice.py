# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt
from erpnext.controllers.selling_controller import SellingController
from erpnext.accounts.utils import get_balance_on_voucher
from frappe.model.mapper import get_mapped_doc


class ProformaInvoice(SellingController):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		self.status_map = [
			["Draft", None],
			["To Bill", "eval:self.docstatus == 1"],
			["Billed", "eval:self.docstatus == 1 and self.billing_status != 'To Bill'"],
			["Cancelled", "eval:self.docstatus == 2"],
		]

	def validate(self):
		super().validate()
		self.validate_uom_is_integer("stock_uom", "qty")
		self.validate_project_customer()
		self.check_sales_order_on_hold_or_close()
		self.validate_campaign()
		self.validate_with_previous_doc()
		self.set_billing_status()
		self.set_outstanding_amount()
		self.set_status()
		self.set_title()

	def before_submit(self):
		self.validate_previous_docstatus()

	def on_submit(self):
		self.update_previous_doc_status()

	def on_cancel(self):
		self.unlink_payments_on_order_cancel()
		self.update_status_on_cancel()
		self.set_outstanding_amount(update=True)
		self.update_previous_doc_status()

	def on_gl_against_voucher(self, account, party_type, party, on_cancel):
		if not party_type or not party:
			return

		self.set_outstanding_amount(update=True)
		self.notify_update()

	def validate_with_previous_doc(self):
		super().validate_with_previous_doc({
			"Sales Order": {
				"ref_dn_field": "sales_order",
				"compare_fields": [["customer", "="], ["company", "="], ["branch", "="], ["project", "="], ["currency", "="]]
			},
			"Sales Order Item": {
				"ref_dn_field": "sales_order_item",
				"compare_fields": [["item_code", "="], ["uom", "="], ["conversion_factor", "="]],
				"is_child_table": True,
				"allow_duplicate_prev_row_id": True
			},
			"Delivery Note": {
				"ref_dn_field": "delivery_note",
				"compare_fields": [["customer", "="], ["company", "="], ["branch", "="], ["project", "="], ["currency", "="]]
			},
			"Delivery Note Item": {
				"ref_dn_field": "delivery_note_item",
				"compare_fields": [["item_code", "="], ["uom", "="], ["conversion_factor", "="],
					["batch_no", "="], ["vehicle", "="]],
				"is_child_table": True,
				"allow_duplicate_prev_row_id": True
			},
			"Packing Slip Item": {
				"ref_dn_field": "packing_slip_item",
				"compare_fields": [["item_code", "="], ["uom", "="], ["conversion_factor", "="],
					["batch_no", "="], ["serial_no", "="], ["net_weight_per_unit", "="]],
				"is_child_table": True,
				"allow_duplicate_prev_row_id": True
			},
		})

		self.validate_packing_slips()

		if cint(frappe.get_cached_value('Selling Settings', None, 'maintain_same_sales_rate')):
			self.validate_rate_with_reference_doc([
				["Sales Order", "sales_order", "sales_order_item"],
				["Delivery Note", "delivery_note", "delivery_note_item"]
			])

	def validate_previous_docstatus(self):
		for d in self.get('items'):
			if d.sales_order and frappe.db.get_value("Sales Order", d.sales_order, "docstatus", cache=1) != 1:
				frappe.throw(_("Row #{0}: Sales Order {1} is not submitted").format(d.idx, d.sales_order))

			if d.delivery_note and frappe.db.get_value("Delivery Note", d.delivery_note, "docstatus", cache=1) != 1:
				frappe.throw(_("Row #{0}: Delivery Note {1} is not submitted").format(d.idx, d.delivery_note))

	def update_previous_doc_status(self):
		sales_orders = set()
		sales_order_row_names_without_dn = set()
		delivery_notes = set()
		delivery_note_row_names = set()

		for d in self.items:
			if d.sales_order:
				sales_orders.add(d.sales_order)
			if d.sales_order_item and not d.delivery_note:
				sales_order_row_names_without_dn.add(d.sales_order_item)
			if d.delivery_note:
				delivery_notes.add(d.delivery_note)
			if d.delivery_note_item:
				delivery_note_row_names.add(d.delivery_note_item)

		# Update Delivery Notes
		for name in delivery_notes:
			doc = frappe.get_doc("Delivery Note", name)
			doc.set_proforma_status(update=True)
			doc.validate_proforma_qty(from_doctype=self.doctype, row_names=delivery_note_row_names)
			doc.set_status(update=True)
			doc.notify_update()

		# Update Sales Orders
		for name in sales_orders:
			doc = frappe.get_doc("Sales Order", name)
			doc.set_proforma_status(update=True)
			doc.validate_proforma_qty(from_doctype=self.doctype, row_names=sales_order_row_names_without_dn)
			doc.set_status(update=True)
			doc.notify_update()

		self.update_project_billing_and_sales(validate_insurance_excess=True)

	def set_billing_status(self, update=False, update_modified=True):
		data = self.get_billing_status_data()

		# update values in rows
		for d in self.items:
			d.billed_qty = flt(data.billed_qty_map.get(d.name))
			d.billed_amt = flt(data.billed_amount_map.get(d.name))
			if update:
				d.db_set({
					'billed_qty': d.billed_qty,
					'billed_amt': d.billed_amt,
				}, update_modified=update_modified)

		# update percentage in parent
		self.per_billed = self.calculate_status_percentage('billed_qty', 'qty', self.items)
		if self.per_billed is None:
			total_billed_qty = flt(sum([flt(d.billed_qty) for d in self.items]), self.precision('total_qty'))
			self.per_billed = 100 if total_billed_qty else 0

		# update billing_status
		self.billing_status = self.get_completion_status('per_billed', 'Bill',
			not_applicable=self.status == "Closed",
			not_applicable_based_on='per_billed')

		if update:
			self.db_set({
				'per_billed': self.per_billed,
				'billing_status': self.billing_status,
			}, update_modified=update_modified)

	def get_billing_status_data(self):
		out = frappe._dict()
		out.billed_qty_map = {}
		out.billed_amount_map = {}

		if self.docstatus == 1:
			row_names = [d.name for d in self.items]
			if row_names:
				# Billed By Sales Invoice
				billed_by_sinv = frappe.db.sql("""
					select i.proforma_invoice_item, i.qty, i.amount
					from `tabSales Invoice Item` i
					inner join `tabSales Invoice` p on p.name = i.parent
					where p.docstatus = 1 and (p.is_return = 0 or p.reopen_order = 1)
						and i.proforma_invoice_item in %s
				""", [row_names], as_dict=1)

				for d in billed_by_sinv:
					out.billed_amount_map.setdefault(d.proforma_invoice_item, 0)
					out.billed_amount_map[d.proforma_invoice_item] += d.amount

					out.billed_qty_map.setdefault(d.proforma_invoice_item, 0)
					out.billed_qty_map[d.proforma_invoice_item] += d.qty

		return out

	def validate_billed_qty(self, from_doctype=None, row_names=None):
		self.validate_completed_qty('billed_qty', 'qty', self.items,
			allowance_type=None, from_doctype=from_doctype, row_names=row_names)

	def set_outstanding_amount(self, update=False, update_modified=True):
		if self.party_account_currency == self.currency:
			grand_total = self.rounded_total or self.grand_total
		else:
			grand_total = self.base_rounded_total or self.base_grand_total

		payable_amount = grand_total - flt(self.total_advance)

		party_type, party, party_name = self.get_billing_party()
		self.advance_paid = get_balance_on_voucher(
			self.doctype,
			self.name,
			party_type,
			party,
			self.debit_to,
			include_original_references=True,
			dr_or_cr="credit_in_account_currency - debit_in_account_currency"
		)

		if self.per_billed or self.docstatus == 2:
			self.outstanding_amount = 0
		else:
			self.outstanding_amount = payable_amount - self.advance_paid

		if update:
			self.db_set({
				"outstanding_amount": self.outstanding_amount,
				"advance_paid": self.advance_paid,
			}, update_modified=update_modified)


@frappe.whitelist()
def make_sales_invoice(
	source_name,
	target_doc=None,
	ignore_permissions=False,
	only_items=None,
	skip_postprocess=False,
):
	if frappe.flags.args and only_items is None:
		only_items = cint(frappe.flags.args.only_items)

	def postprocess(source, target):
		target.flags.ignore_permissions = ignore_permissions
		target.ignore_pricing_rule = 1
		target.update_stock = 0
		target.run_method("postprocess_after_mapping")

	mapping = {
		"Proforma Invoice": {
			"doctype": "Sales Invoice",
			"field_map": {
				"remarks": "remarks",
			},
			"validation": {
				"docstatus": ["=", 1],
			}
		},
		"Proforma Invoice Item": get_item_mapper_for_invoice(),
		"Sales Taxes and Charges": {
			"doctype": "Sales Taxes and Charges",
			"add_if_empty": True
		},
		"Sales Team": {
			"doctype": "Sales Team",
			"field_map": {
				"incentives": "incentives"
			},
			"add_if_empty": True
		}
	}

	frappe.utils.call_hook_method("update_sales_invoice_from_proforma_invoice_mapper", mapping, "Sales Invoice")

	if only_items:
		mapping = {dt: dt_mapping for dt, dt_mapping in mapping.items() if dt == "Proforma Invoice Item"}

	doc = get_mapped_doc(
		"Proforma Invoice",
		source_name,
		mapping,
		target_doc=target_doc,
		ignore_permissions=ignore_permissions,
		postprocess=postprocess if not skip_postprocess else None,
		explicit_child_tables=only_items,
	)

	return doc


def get_item_mapper_for_invoice(allow_duplicate=False):
	def item_condition(source, source_parent, target_parent):
		if not allow_duplicate:
			if source.name in [d.proforma_invoice_item for d in target_parent.get('items') if d.proforma_invoice_item]:
				return False

		to_bill_qty = flt(source.qty) - flt(source.billed_qty)
		return to_bill_qty > 0

	def update_item(source, target, source_parent, target_parent):
		target.project = source_parent.get('project')

	return {
		"doctype": "Sales Invoice Item",
		"field_map": {
			"name": "proforma_invoice_item",
			"parent": "proforma_invoice",
			"delivery_note_item": "delivery_note_item",
			"delivery_note": "delivery_note",
			"sales_order": "sales_order",
			"sales_order_item": "sales_order_item",
			"quotation": "quotation",
			"quotation_item": "quotation_item",
			"packing_slip": "packing_slip",
			"packing_slip_item": "packing_slip_item",
			"batch_no": "batch_no",
			"serial_no": "serial_no",
			"vehicle": "vehicle",
		},
		"postprocess": update_item,
		"condition": item_condition,
	}
