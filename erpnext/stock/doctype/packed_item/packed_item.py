# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cstr, flt
from erpnext.stock.get_item_details import get_item_details, get_default_warehouse
from frappe.model.document import Document
import json


class PackedItem(Document):
	pass


def get_product_bundle_items(item_code):
	return frappe.db.sql("""
		select t1.item_code, t1.qty, t1.uom, t1.type, t1.item_group
		from `tabProduct Bundle Item` t1, `tabProduct Bundle` t2
		where t2.new_item_code = %s and t1.parent = t2.name
		order by t1.idx
	""", item_code, as_dict=1)


def get_packing_item_details(item, company):
	item_details = frappe.get_cached_doc("Item", item).as_dict()
	item_details.default_warehouse = get_default_warehouse(item, {'company': company})
	return item_details


def get_bin_qty(item, warehouse):
	det = frappe.db.sql("""select actual_qty, projected_qty from `tabBin`
		where item_code = %s and warehouse = %s""", (item, warehouse), as_dict = 1)
	return det and det[0] or frappe._dict()


def update_packing_list_item(doc, packing_item_code, qty, main_item_row, packed_item_qty=None):
	if doc.amended_from:
		old_packed_items_map = get_old_packed_item_details(doc.packed_items)
	else:
		old_packed_items_map = False
	item = get_packing_item_details(packing_item_code, doc.company)

	# check if exists
	exists = 0
	for d in doc.get("packed_items"):
		if d.parent_item == main_item_row.item_code and d.item_code == packing_item_code and\
				d.parent_detail_docname == main_item_row.name:
			pi, exists = d, 1
			break

	if not exists:
		pi = doc.append('packed_items', {})

	pi.parent_item = main_item_row.item_code
	pi.item_code = packing_item_code
	pi.item_name = item.item_name
	pi.parent_detail_docname = main_item_row.name
	pi.uom = item.stock_uom
	pi.qty = flt(qty)

	if doc.doctype == "Sales Order":
		pi.allow_select_item_code = 1
		pi.allow_edit_qty = 0
		pi.qty = flt(qty)

	if doc.doctype == "Delivery Note":
		pi.allow_select_item_code = 0
		pi.allow_edit_qty = 1
		pi.qty = get_final_qty(qty, packed_item_qty)

	if not pi.warehouse and not doc.amended_from:
		pi.warehouse = (main_item_row.warehouse if ((doc.get('is_pos') or item.is_stock_item \
			or not item.default_warehouse) and main_item_row.warehouse) else item.default_warehouse)
	if not pi.batch_no and not doc.amended_from:
		pi.batch_no = cstr(main_item_row.get("batch_no"))
	if not pi.target_warehouse:
		pi.target_warehouse = main_item_row.get("target_warehouse")
	bin = get_bin_qty(packing_item_code, pi.warehouse)
	pi.actual_qty = flt(bin.get("actual_qty"))
	pi.projected_qty = flt(bin.get("projected_qty"))
	if old_packed_items_map and old_packed_items_map.get((packing_item_code, main_item_row.item_code)):
		pi.batch_no = old_packed_items_map.get((packing_item_code, main_item_row.item_code))[0].batch_no
		pi.serial_no = old_packed_items_map.get((packing_item_code, main_item_row.item_code))[0].serial_no
		pi.warehouse = old_packed_items_map.get((packing_item_code, main_item_row.item_code))[0].warehouse

def get_final_qty(qty, packed_item_qty):
	if packed_item_qty is None:
		return flt(qty)
	qty = flt(qty)
	packed_item_qty = flt(packed_item_qty)
	return qty if flt(qty) == flt(packed_item_qty) else flt(packed_item_qty)

def make_packing_list(doc):
	"""Create packing list for Product Bundle items."""
	if doc.get("_action") == "update_after_submit":
		return

	parent_items = []

	for item in doc.get("items", []):
		if not is_product_bundle(item.item_code):
			continue

		for bundle_item in get_product_bundle_items(item.item_code):
			if bundle_item.type == "Item":
				add_bundle_item(doc, bundle_item, item)
			elif bundle_item.type == "Item Group":
				add_bundle_group(doc, bundle_item, item)

		if [item.item_code, item.name] not in parent_items:
			parent_items.append([item.item_code, item.name])

	cleanup_packing_list(doc, parent_items)


def is_product_bundle(item_code):
	"""Check if an item is a product bundle."""
	return frappe.db.exists("Product Bundle", {"new_item_code": item_code})


def add_bundle_item(doc, bundle_item, parent_item):
	"""Add a bundled item (type: Item) to the packing list."""
	qty = flt(bundle_item.qty) * flt(parent_item.stock_qty)
	update_packing_list_item(doc, bundle_item.item_code, qty, parent_item)


def add_bundle_group(doc, bundle_item, parent_item):
	"""Handle bundled item of type 'Item Group'."""
	bundle_qty = flt(bundle_item.qty) or 1
	total_qty = bundle_qty * flt(parent_item.stock_qty)

	packed_items = doc.get("packed_items") or []

	if not packed_items:
		packed_item = doc.append("packed_items", {})
		packed_item.parent_item = parent_item.item_code
		packed_item.parent_detail_docname = parent_item.name
		packed_item.item_group = bundle_item.item_group
		packed_item.qty = total_qty
		packed_item.type = "Item Group"
	else:
		for packed_item in packed_items:
			if packed_item.item_code:
				update_packing_list_item(doc, packed_item.item_code, flt(bundle_item.qty) * flt(parent_item.stock_qty),
					parent_item, packed_item_qty=packed_item.qty)


def cleanup_packing_list(doc, parent_items):
	"""Remove all those child items which are no longer present in main item table"""
	delete_list = []
	for d in doc.get("packed_items"):
		if [d.parent_item, d.parent_detail_docname] not in parent_items:
			# mark for deletion from doclist
			delete_list.append(d)

	if not delete_list:
		return doc

	packed_items = doc.get("packed_items")
	doc.set("packed_items", [])
	for d in packed_items:
		if d not in delete_list:
			doc.append("packed_items", d)


@frappe.whitelist()
def get_items_from_product_bundle(args):
	args = json.loads(args)
	items = []
	bundled_items = get_product_bundle_items(args["item_code"])
	for item in bundled_items:
		args.update({
			"item_code": item.item_code,
			"qty": flt(args["quantity"]) * flt(item.qty)
		})
		items.append(get_item_details(args))

	return items


def on_doctype_update():
	frappe.db.add_index("Packed Item", ["item_code", "warehouse"])


def get_old_packed_item_details(old_packed_items):
	old_packed_items_map = {}
	for items in old_packed_items:
		old_packed_items_map.setdefault((items.item_code ,items.parent_item), []).append(items.as_dict())
	return old_packed_items_map

def validate_packed_items_for_bundles(doc):
	"""Validate that all product bundles have proper packed items"""
	for item in doc.get("items"):
		if not frappe.db.exists('Product Bundle', item.item_code):
			continue

		packed_items = get_packed_items_for_bundle(doc, item)

		if not packed_items:
			make_packing_list(doc)
			packed_items = get_packed_items_for_bundle(doc, item)

		if not packed_items:
			frappe.throw(_("Row #{0}: Product Bundle {1} has no packed items").format(
				item.idx, item.item_code
			))

		bundle = frappe.get_doc('Product Bundle', item.item_code)
		required_items = build_required_items_map(bundle, item.qty)

		validate_packed_items(packed_items, required_items, item)


def get_packed_items_for_bundle(doc, item):
	return [d for d in doc.get("packed_items") if d.parent_detail_docname == item.name]


def build_required_items_map(bundle, item_qty):
	required_items = {}
	for bundle_item in bundle.items:
		key = bundle_item.item_code if bundle_item.type == 'Item' else bundle_item.item_group
		data = {
			'qty': flt(bundle_item.qty) * flt(item_qty),
			'type': bundle_item.type
		}
		required_items[key] = data
	return required_items


def validate_packed_items(packed_items, required_items, item):
	for packed_item in packed_items:
		if packed_item.type == 'Item':
			validate_individual_packed_item(packed_item, required_items, item)
		elif packed_item.type == 'Item Group':
			validate_packed_item_group(packed_item, required_items, item)


def validate_individual_packed_item(packed_item, required_items, item):
	item_code = packed_item.item_code
	item_group = frappe.get_cached_value('Item', item_code, 'item_group')

	found = False
	# Try to match to an item group
	for req_key, req_data in required_items.items():
		if req_data['type'] == 'Item Group' and item_group == req_key:
			found = True
			break

	# Try to match to a direct item
	if not found and item_code in required_items:
		expected_qty = required_items[item_code]['qty']
		if flt(packed_item.qty) != expected_qty:
			frappe.throw(_("Row #{0}: Quantity mismatch for item {1} in bundle {2}").format(
				item.idx, item_code, item.item_code
			))
		found = True

	if not found:
		frappe.throw(_("Row #{0}: Item {1} is not part of bundle {2}").format(
			item.idx, item_code, item.item_code
		))


def validate_packed_item_group(packed_item, required_items, item):
	if not packed_item.item_code:
		frappe.throw(_("Row #{0} (Packed Item for {1}): Please select an Item for Item Group {2}").format(
			item.idx, item.item_code, packed_item.item_group
		))

	if packed_item.item_group not in required_items:
		frappe.throw(_("Row #{0}: Item Group {1} is not part of bundle {2}").format(
			item.idx, packed_item.item_group, item.item_code
		))
