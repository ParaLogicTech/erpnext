# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from frappe.model.document import Document
from erpnext.stock.get_item_details import get_item_details, get_default_warehouse
from erpnext.setup.doctype.item_group.item_group import get_item_group_subtree
import json


class PackedItem(Document):
	pass


def make_bundled_item_list(doc):
	"""Create packing list for Product Bundle items."""
	if doc.get("_action") == "update_after_submit":
		return

	for parent_row in doc.get("items", []):
		if not is_product_bundle(parent_row.item_code):
			continue

		if doc.doctype in ("Delivery Note", "Sales Invoice") and parent_row.get("sales_order") and parent_row.get("sales_order_item"):
			sales_order_bundled_items = get_sales_order_bundled_items(parent_row.sales_order, parent_row.sales_order_item)
			for bundle_row in sales_order_bundled_items:
				update_child_item_row(doc, bundle_row, parent_row, previous_detail_docname=bundle_row.name)
		else:
			for bundle_row in get_product_bundle_items(parent_row.item_code):
				if bundle_row.type == "Item":
					update_child_item_row(doc, bundle_row, parent_row)
				elif bundle_row.type == "Item Group":
					update_child_item_group_row(doc, bundle_row, parent_row)

	cleanup_packing_list(doc)


def update_child_item_row(doc, bundle_row, parent_row, previous_detail_docname=None):
	child_row = None
	for d in doc.get("packed_items"):
		if d.parent_item != parent_row.item_code or d.item_code != bundle_row.item_code:
			continue

		if doc.is_new():
			if d.flags.is_updated:
				continue
		else:
			if d.parent_detail_docname != parent_row.name:
				continue

		child_row = d
		break

	if not child_row:
		child_row = doc.append('packed_items')
		set_child_row_balance_qty(doc, bundle_row, child_row)

	update_packing_list_item(doc, bundle_row, parent_row, child_row, previous_detail_docname=previous_detail_docname)


def update_child_item_group_row(doc, bundle_row, parent_row):
	child_row = None
	for d in doc.get("packed_items"):
		if d.parent_item != parent_row.item_code or d.item_group != bundle_row.item_group:
			continue

		if doc.is_new():
			if d.flags.is_updated:
				continue
		else:
			if d.parent_detail_docname != parent_row.name:
				continue

		child_row = d
		break

	if not child_row:
		child_row = doc.append('packed_items')

	update_packing_list_item(doc, bundle_row, parent_row, child_row)


def set_child_row_balance_qty(doc, bundle_row, child_row):
	if (
		(doc.doctype == "Delivery Note" or (doc.doctype == "Sales Invoice" and doc.update_stock))
		and bundle_row.doctype == "Packed Item"
	):
		child_row.qty = max(0, bundle_row.qty - bundle_row.delivered_qty)


def update_packing_list_item(doc, bundle_row, parent_row, child_row, previous_detail_docname=None):
	from erpnext.stock.get_item_details import get_bin_details

	child_row.type = bundle_row.type
	child_row.parent_item = parent_row.item_code
	child_row.parent_item_name = parent_row.item_name
	child_row.parent_detail_docname = parent_row.name
	child_row.previous_detail_docname = previous_detail_docname

	if bundle_row.type == "Item":
		child_row.item_code = bundle_row.item_code
		child_row.item_group = None
	elif bundle_row.type == "Item Group":
		child_row.item_group = bundle_row.item_group
		if previous_detail_docname and bundle_row.item_code:
			child_row.item_code = bundle_row.item_code

	# Allow editing qty
	if (
		not bundle_row.qty
		or (doc.doctype == "Delivery Note" and parent_row.get("sales_order"))
		or (doc.doctype == "Sales Invoice" and (parent_row.get("sales_order") or parent_row.get("delivery_note")))
		or doc.get("is_return")
	):
		child_row.allow_edit_qty = 1
	else:
		child_row.allow_edit_qty = 0

	# Allow selecting item code
	if (
		bundle_row.type == "Item Group"
		and not (doc.doctype == "Delivery Note" and parent_row.get("sales_order"))
		and not (doc.doctype == "Sales Invoice" and (parent_row.get("sales_order") or parent_row.get("delivery_note")))
	):
		child_row.allow_select_item_code = 1
	else:
		child_row.allow_select_item_code = 0

	item = frappe.get_cached_doc("Item", child_row.item_code) if child_row.item_code else frappe._dict()

	child_row.item_name = item.item_name
	child_row.uom = item.stock_uom

	child_row.is_stock_item = item.is_stock_item
	child_row.has_batch_no = item.has_batch_no
	child_row.has_serial_no = item.has_serial_no

	if not child_row.allow_edit_qty:
		child_row.qty = flt(flt(bundle_row.qty) * flt(parent_row.stock_qty), 6)

	child_row.stock_qty = flt(child_row.qty, 6)

	if not child_row.warehouse:
		if parent_row.warehouse:
			child_row.warehouse = parent_row.warehouse
		elif item.is_stock_item:
			args = doc.get_item_details_child_args(parent_row, doc.get_item_details_parent_args())
			child_row.warehouse = get_default_warehouse(item, args, overwrite_warehouse=False)

	if parent_row.get("target_warehouse"):
		child_row.target_warehouse = parent_row.get("target_warehouse")
	else:
		child_row.target_warehouse = None

	bin_details = get_bin_details(child_row.item_code, child_row.warehouse)
	child_row.actual_qty = flt(bin_details.get("actual_qty"))
	child_row.projected_qty = flt(bin_details.get("projected_qty"))

	if doc.doctype == "Delivery Note" or (doc.doctype == "Sales Invoice" and doc.update_stock) and doc.docstatus == 1:
		child_row.delivered_qty = child_row.qty

	child_row.flags.is_updated = True
	child_row.flags.parent_row = parent_row


def cleanup_packing_list(doc):
	def sorter(row):
		parent_row = get_parent_row_from_child_row(doc, row) or frappe._dict()
		bundle_row = get_bundle_row_from_child_row(doc, row) or frappe._dict()
		return parent_row.idx or 99999, bundle_row.idx or 99999

	delete_list = []
	for child_row in doc.get("packed_items"):
		parent_row = get_parent_row_from_child_row(doc, child_row)
		bundle_row = get_bundle_row_from_child_row(doc, child_row)
		if not child_row.parent_item:
			delete_list.append(child_row)
		elif not parent_row or not bundle_row:
			delete_list.append(child_row)

	for child_row in delete_list:
		doc.remove(child_row)

	doc.packed_items = sorted(doc.get("packed_items"), key=lambda d: sorter(d))
	for i, child_row in enumerate(doc.get("packed_items")):
		child_row.flags.is_updated = None
		child_row.idx = i + 1


def get_bundle_row_from_child_row(doc, child_row):
	if not child_row.parent_item:
		return None

	product_bundle = get_product_bundle_from_item_code(child_row.parent_item)
	if product_bundle:
		bundle_doc = frappe.get_cached_doc("Product Bundle", product_bundle)
		parent_row = get_parent_row_from_child_row(doc, child_row)

		if (
			doc.doctype in ("Delivery Note", "Sales Invoice")
			and parent_row
			and parent_row.get("sales_order")
			and parent_row.get("sales_order_item")
		):
			bundled_items = get_sales_order_bundled_items(parent_row.sales_order, parent_row.sales_order_item)
		else:
			bundled_items = bundle_doc.get("items")

		for bundle_row in bundled_items:
			if child_row.type == "Item" and bundle_row.item_code == child_row.item_code:
				return bundle_row
			if child_row.type == "Item Group" and bundle_row.item_group == child_row.item_group:
				return bundle_row


def get_parent_row_from_child_row(doc, child_row):
	if not child_row.parent_item:
		return None
	if doc.name and not child_row.parent_detail_docname:
		return None

	for parent_row in doc.get("items"):
		if parent_row.item_code != child_row.parent_item:
			continue

		if doc.name:
			if parent_row.name == child_row.parent_detail_docname:
				return parent_row
		elif child_row.flags.parent_row:
			return child_row.flags.parent_row


@frappe.whitelist()
def get_items_from_product_bundle(args):
	if isinstance(args, str):
		args = json.loads(args)

	items = []
	bundled_items = get_product_bundle_items(args["item_code"])
	for item in bundled_items:
		if item.item_code:
			args.update({
				"item_code": item.item_code,
				"qty": flt(args["quantity"]) * flt(item.qty)
			})
			items.append(get_item_details(args))

	return items


def validate_bundled_item_list(doc):
	for parent_row in doc.get("items"):
		validate_bundled_items_for_parent_row(doc, parent_row)


def validate_bundled_items_for_parent_row(doc, parent_row):
	if not is_product_bundle(parent_row.item_code):
		return

	child_rows = [d for d in doc.get("packed_items")
		if d.parent_detail_docname == parent_row.name and d.parent_item == parent_row.item_code]

	for child_row in child_rows:
		if not child_row.item_code and doc.docstatus == 1:
			frappe.throw(_("Bundled Item Row #{0}: Please select Bundled Item for Parent Item {1} for Item Group {2}").format(
				child_row.idx, frappe.bold(parent_row.item_code), frappe.bold(child_row.item_group)
			))

		if child_row.type == "Item Group" and child_row.item_code and child_row.item_group:
			allowed_item_groups = get_item_group_subtree(child_row.item_group)
			child_item_group = frappe.get_cached_value("Item", child_row.item_code, "item_group")
			if child_item_group not in allowed_item_groups:
				frappe.throw(_("Bundled Item Row #{0}: Bundled Item {1} does not belong to Item Group {2}").format(
					child_row.idx, frappe.bold(child_row.item_code), frappe.bold(child_row.item_group)
				))

		if child_row.allow_edit_qty and child_row.item_code:
			if doc.get("is_return"):
				if flt(child_row.qty) > 0:
					frappe.throw(_("Bundled Item Row #{0}: Bundled Item {1} Qty must be negative for return").format(
						child_row.idx, frappe.bold(child_row.item_code)
					))
			else:
				if flt(child_row.qty) < 0:
					frappe.throw(_("Bundled Item Row #{0}: Bundled Item {1} Qty can not be negative").format(
						child_row.idx, frappe.bold(child_row.item_code)
					))


def get_product_bundle_items(item_code):
	product_bundle = get_product_bundle_from_item_code(item_code)
	if not product_bundle:
		return []

	bundle_doc = frappe.get_cached_doc("Product Bundle", product_bundle)
	return bundle_doc.items


def get_sales_order_bundled_items(sales_order, sales_order_item):
	def generator():
		return frappe.db.sql("""
			select *
			from `tabPacked Item`
			where parenttype = 'Sales Order'
				and parent = %(sales_order)s
				and parent_detail_docname = %(sales_order_item)s
		""", {
			"sales_order": sales_order,
			"sales_order_item": sales_order_item,
		}, update={"doctype": "Packed Item"}, as_dict=1)

	return frappe.local_cache("get_sales_order_bundled_items", (sales_order, sales_order_item), generator)


def is_product_bundle(item_code, cache=True):
	return 1 if get_product_bundle_from_item_code(item_code, cache=cache) else 0


def get_product_bundle_from_item_code(item_code, cache=True):
	if not item_code:
		return None

	def generator():
		return frappe.db.get_value("Product Bundle", {"new_item_code": item_code})

	if cache:
		return frappe.local_cache("get_product_bundle_from_item_code", item_code, generator)
	else:
		return generator()


def on_doctype_update():
	frappe.db.add_index("Packed Item", ["item_code", "warehouse"])