# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint
from erpnext.controllers.selling_controller import SellingController
from frappe.model.mapper import get_mapped_doc


class ProformaInvoice(SellingController):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		self.status_map = [
			["Draft", None],
			["To Bill", "eval:self.docstatus == 1"],
			["Cancelled", "eval:self.docstatus == 2"],
		]

	def validate(self):
		super().validate()
		self.validate_uom_is_integer("stock_uom", "qty")
		self.validate_project_customer()
		self.check_sales_order_on_hold_or_close()
		self.validate_campaign()
		self.validate_with_previous_doc()
		# self.set_billing_status()
		self.set_status()
		self.set_title()

	def before_submit(self):
		self.validate_previous_docstatus()

	def on_submit(self):
		self.update_previous_doc_status()

	def on_cancel(self):
		self.update_status_on_cancel()
		self.update_previous_doc_status()

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

		# self.update_project_billing_and_sales()


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None, only_items=None, skip_postprocess=False):
	if frappe.flags.args and only_items is None:
		only_items = cint(frappe.flags.args.only_items)

	def postprocess(source, target):
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
		"Proform Invoice Item": get_item_mapper_for_invoice(),
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

	doc = get_mapped_doc("Proforma Invoice", source_name, mapping, target_doc,
		postprocess=postprocess if not skip_postprocess else None,
		explicit_child_tables=only_items)

	return doc


def get_item_mapper_for_invoice(allow_duplicate=False):
	def item_condition(source, source_parent, target_parent):
		if not allow_duplicate:
			if source.name in [d.proforma_invoice_item for d in target_parent.get('items') if d.proforma_invoice_item]:
				return False

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
