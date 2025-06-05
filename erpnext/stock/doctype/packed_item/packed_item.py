# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

# For license information, please see license.txt

import frappe
from frappe.utils import cstr, flt
from erpnext.stock.get_item_details import get_item_details, get_default_warehouse
from frappe.model.document import Document
import json
from frappe import _


class PackedItem(Document):
	pass


def get_product_bundle_items(item_code):
	return frappe.db.sql("""select t1.item_code, t1.qty, t1.uom, t1.description, t1.type, t1.item_group
		from `tabProduct Bundle Item` t1, `tabProduct Bundle` t2
		where t2.new_item_code=%s and t1.parent = t2.name order by t1.idx""", item_code, as_dict=1)


def get_packing_item_details(item, company):
	item_details = frappe.get_cached_doc("Item", item).as_dict()
	item_details.default_warehouse = get_default_warehouse(item, {'company': company})
	return item_details


def get_bin_qty(item, warehouse):
	det = frappe.db.sql("""select actual_qty, projected_qty from `tabBin`
		where item_code = %s and warehouse = %s""", (item, warehouse), as_dict = 1)
	return det and det[0] or frappe._dict()


def update_packing_list_item(doc, packing_item_code, qty, main_item_row, description):
	"""Update a single packed item"""
	doc = frappe._dict(json.loads(doc)) if isinstance(doc, str) else doc
	main_item_row = frappe._dict(json.loads(main_item_row)) if isinstance(main_item_row, str) else main_item_row

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
	if description and not pi.description:
		pi.description = description
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

	return doc


def make_packing_list(doc):
	"""make packing list for Product Bundle item"""
	if doc.get("_action") and doc._action == "update_after_submit":
		return

	parent_items = get_parent_items(doc)
	existing_packed_items = doc.get("packed_items", [])
	is_first_creation = len(existing_packed_items) == 0

	# Create tracking system
	processed_items = {}
	doc.set("packed_items", [])

	# Process each item
	for item in doc.get("items"):
		if not is_product_bundle(item.item_code):
			continue
		process_bundle_item(doc, item, existing_packed_items, processed_items, is_first_creation)

	# Add back unprocessed items
	add_unprocessed_items(doc, existing_packed_items, processed_items)
	cleanup_packing_list(doc, parent_items)


def get_parent_items(doc):
	"""Get list of parent items that are product bundles"""
	parent_items = []
	for d in doc.get("items"):
		if is_product_bundle(d.item_code):
			parent_items.append([d.item_code, d.name])
	return parent_items


def is_product_bundle(item_code):
	"""Check if item is a product bundle"""
	return frappe.db.get_value("Product Bundle", {"new_item_code": item_code})


def process_bundle_item(doc, item, existing_packed_items, processed_items, is_first_creation):
	"""Process a single bundle item and its packed items"""
	bundle_items = get_product_bundle_items(item.item_code)

	for bundle_item in bundle_items:
		key = (item.item_code, item.name, bundle_item.item_code if bundle_item.type == "Item" else bundle_item.item_group)

		if key in processed_items:
			continue

		if bundle_item.type == "Item":
			process_individual_item(doc, item, bundle_item, existing_packed_items, is_first_creation)
		elif bundle_item.type == "Item Group":
			process_item_group(doc, item, bundle_item, existing_packed_items, is_first_creation)

		processed_items[key] = True


def process_individual_item(doc, parent_item, bundle_item, existing_packed_items, is_first_creation):
	"""Process an individual item in the bundle"""
	existing_item = find_existing_packed_item(existing_packed_items, parent_item, bundle_item.item_code)

	if existing_item:
		doc.append('packed_items', existing_item)
	elif is_first_creation:
		qty = calculate_packed_qty(bundle_item.qty, parent_item.stock_qty)
		update_packing_list_item(doc, bundle_item.item_code, qty, parent_item, bundle_item.description)


def process_item_group(doc, parent_item, bundle_item, existing_packed_items, is_first_creation):
	"""Process an item group in the bundle"""
	existing_group_items = find_existing_group_items(existing_packed_items, parent_item, bundle_item.item_group)

	if existing_group_items:
		for existing_item in existing_group_items:
			doc.append('packed_items', existing_item)
	elif is_first_creation:
		create_empty_item_group_row(doc, parent_item, bundle_item)


def find_existing_packed_item(existing_packed_items, parent_item, item_code):
	"""Find existing packed item for a specific item code"""
	return next((ep for ep in existing_packed_items
		if ep.parent_item == parent_item.item_code
		and ep.item_code == item_code
		and ep.parent_detail_docname == parent_item.name), None)


def find_existing_group_items(existing_packed_items, parent_item, item_group):
	"""Find existing packed items for an item group"""
	return [ep for ep in existing_packed_items
		if ep.parent_item == parent_item.item_code
		and ep.parent_detail_docname == parent_item.name
		and ep.item_group == item_group]


def create_empty_item_group_row(doc, parent_item, bundle_item):
	"""Create an empty row for item group selection"""
	pi = doc.append('packed_items', {})
	pi.parent_item = parent_item.item_code
	pi.parent_detail_docname = parent_item.name
	pi.item_group = bundle_item.item_group
	pi.qty = calculate_packed_qty(bundle_item.qty, parent_item.stock_qty)
	pi.description = bundle_item.description
	pi.type = "Item Group"


def calculate_packed_qty(bundle_qty, parent_qty):
	"""Calculate the packed item quantity based on bundle and parent quantities.
	If bundle_qty is zero, use 1 as the default quantity."""
	bundle_qty = 1 if flt(bundle_qty) == 0 else flt(bundle_qty)
	return bundle_qty * flt(parent_qty)


def add_unprocessed_items(doc, existing_packed_items, processed_items):
	"""Add back any existing items that weren't processed"""
	for ep in existing_packed_items:
		key = (ep.parent_item, ep.parent_detail_docname, ep.item_code if ep.type == "Item" else ep.item_group)
		if key not in processed_items:
			doc.append('packed_items', ep)


def cleanup_packing_list(doc, parent_items):
	"""Remove all those child items which are no longer present in main item table"""
	delete_list = []
	for d in doc.get("packed_items"):
		# Only consider for deletion if parent_detail_docname is set
		if not d.parent_detail_docname:
			# Optionally log a warning here
			continue
		if [d.parent_item, d.parent_detail_docname] not in parent_items:
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


def validate_item_group_quantities(required_items, item, doc):
	for req_group, req_data in required_items.items():
		if req_data['type'] == 'Item Group':
			# Get all packed items for this group from the parent document
			group_items = [d for d in doc.get("packed_items")
				if d.parent_detail_docname == item.name and d.item_group == req_group]
			total_qty = sum(flt(d.qty) for d in group_items)

			if abs(total_qty - req_data['qty']) >=0.0001:
				frappe.throw(_("Row #{0}: Total quantity of items from group {1} ({2}) does not match required quantity ({3})").format(
					item.idx, req_group, total_qty, req_data['qty']
				))


def update_delivery_status(doc):
	"""Update delivery status based on packed items"""
	for item in doc.get("items"):
		if frappe.db.exists('Product Bundle', item.item_code):
			packed_items = [d for d in doc.get("packed_items") if d.parent_detail_docname == item.name]
			if packed_items:
				total_delivered = sum(flt(d.delivered_qty) for d in packed_items)
				total_required = sum(flt(d.qty) for d in packed_items)
				
				if total_delivered >= total_required:
					item.delivery_status = "Fully Delivered"
				elif total_delivered > 0:
					item.delivery_status = "Partially Delivered"
				else:
					item.delivery_status = "Not Delivered"
				
				item.delivered_qty = total_delivered