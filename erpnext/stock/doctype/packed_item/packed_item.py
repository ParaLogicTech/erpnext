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
	if doc.get("_action") and doc._action == "update_after_submit": return

	parent_items = []
	existing_packed_items = doc.get("packed_items", [])
	is_first_creation = len(existing_packed_items) == 0

	# Create a more comprehensive tracking system
	processed_items = {}  # Use dict instead of set for better tracking
	manual_items = []

	# Store parent items first
	for d in doc.get("items"):
		if frappe.db.get_value("Product Bundle", {"new_item_code": d.item_code}):
			parent_items.append([d.item_code, d.name])

	# Clear only the items that need to be updated
	doc.set("packed_items", [])

	for d in doc.get("items"):
		if frappe.db.get_value("Product Bundle", {"new_item_code": d.item_code}):
			bundle_items = get_product_bundle_items(d.item_code)
			for i in bundle_items:
				key = (d.item_code, d.name, i.item_code if i.type == "Item" else i.item_group)
				
				# Check if this item was already processed
				if key in processed_items:
					continue

				if i.type == "Item":
					# Always look for existing item first
					existing_item = next((ep for ep in existing_packed_items 
						if ep.parent_item == d.item_code 
						and ep.item_code == i.item_code 
						and ep.parent_detail_docname == d.name), None)
					
					if existing_item:
						# Update existing item
						doc.append('packed_items', existing_item)
					elif is_first_creation:
						# Only create new item on first creation
						update_packing_list_item(doc, i.item_code, 
							flt(i.qty)*flt(d.stock_qty), d, i.description)
					
					processed_items[key] = True
				
				elif i.type == "Item Group":
					# For item groups, we need to handle differently
					# First check if we have any existing items for this group
					existing_group_items = [ep for ep in existing_packed_items 
						if ep.parent_item == d.item_code 
						and ep.parent_detail_docname == d.name
						and ep.item_group == i.item_group]
					
					if existing_group_items:
						# If we have existing items, use them
						for existing_item in existing_group_items:
							doc.append('packed_items', existing_item)
					elif is_first_creation:
						# On first creation, create an empty row for item selection
						pi = doc.append('packed_items', {})
						pi.parent_item = d.item_code
						pi.parent_detail_docname = d.name
						pi.item_group = i.item_group
						pi.qty = flt(i.qty)*flt(d.stock_qty)
						pi.description = i.description
						pi.type = "Item Group"
						# Don't set item_code - let user select it
					
					processed_items[key] = True

	# Add back manual items and any existing items that weren't processed
	for ep in existing_packed_items:
		key = (ep.parent_item, ep.parent_detail_docname, 
			   ep.item_code if ep.type == "Item" else ep.item_group)
		if key not in processed_items:
			doc.append('packed_items', ep)

	cleanup_packing_list(doc, parent_items)


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


@frappe.whitelist()
def update_packing_list_item_from_selection(doc, selected_items):
	"""Update packed items based on user selection from item group"""
	doc = frappe._dict(json.loads(doc)) if isinstance(doc, str) else doc
	selected_items = json.loads(selected_items) if isinstance(selected_items, str) else selected_items

	# Store existing packed items
	existing_packed_items = doc.get("packed_items", [])
	
	# Clear only the item group rows that are being updated
	doc.set("packed_items", [d for d in existing_packed_items if d.type != "Item Group"])

	for item in selected_items:
		main_item_row = frappe._dict({
			'item_code': item.get('parent_item'),
			'name': item.get('parent_detail_docname'),
			'warehouse': doc.get('warehouse'),
			'batch_no': doc.get('batch_no'),
			'target_warehouse': doc.get('target_warehouse')
		})

		# Look for existing item with same parent and item_group
		existing_item = next((ep for ep in existing_packed_items 
			if ep.parent_item == item.get('parent_item')
			and ep.parent_detail_docname == item.get('parent_detail_docname')
			and ep.item_group == item.get('item_group')), None)

		if existing_item:
			# Update existing item
			existing_item.item_code = item.get('item_code')
			existing_item.item_name = item.get('item_name')
			existing_item.qty = flt(item.get('qty'))
			if item.get('description'):
				existing_item.description = item.get('description')
			doc.append('packed_items', existing_item)
		else:
			# Create new item if not found
			update_packing_list_item(doc, item.get('item_code'), item.get('qty'), main_item_row, item.get('description'))

	return doc


def validate_packed_items_for_bundles(doc):
	"""Validate that all product bundles have proper packed items"""
	for item in doc.get("items"):
		if frappe.db.exists('Product Bundle', item.item_code):
			# Get packed items for this bundle
			packed_items = [d for d in doc.get("packed_items") if d.parent_detail_docname == item.name]
			if not packed_items:
				# Try to auto-generate the packing list if missing
				make_packing_list(doc)
				packed_items = [d for d in doc.get("packed_items") if d.parent_detail_docname == item.name]
				if not packed_items:
					frappe.throw(_("Row #{0}: Product Bundle {1} has no packed items").format(
						item.idx, item.item_code
					))

			# Get product bundle details
			bundle = frappe.get_doc('Product Bundle', item.item_code)
			required_items = {}
			
			# Build required items map
			for bundle_item in bundle.items:
				if bundle_item.type == 'Item':
					required_items[bundle_item.item_code] = {
						'qty': flt(bundle_item.qty) * flt(item.qty),
						'type': 'Item'
					}
				elif bundle_item.type == 'Item Group':
					required_items[bundle_item.item_group] = {
						'qty': flt(bundle_item.qty) * flt(item.qty),
						'type': 'Item Group',
						'selected_items': []
					}

			# Validate packed items
			for packed_item in packed_items:
				if packed_item.type == 'Item':
					item_code = packed_item.item_code
					item_group = frappe.get_cached_value('Item', item_code, 'item_group')
					
					# Check if item belongs to any required item group
					found = False
					for req_group, req_data in required_items.items():
						if req_data['type'] == 'Item Group' and item_group == req_group:
							req_data['selected_items'].append({
								'item_code': item_code,
								'qty': flt(packed_item.qty)
							})
							found = True
							break
					
					# If not found in any group, check if it's a direct item requirement
					if not found and item_code in required_items:
						if flt(packed_item.qty) != required_items[item_code]['qty']:
							frappe.throw(_("Row #{0}: Quantity mismatch for item {1} in bundle {2}").format(
								item.idx, item_code, item.item_code
							))
						found = True
					
					if not found:
						frappe.throw(_("Row #{0}: Item {1} is not part of bundle {2}").format(
							item.idx, item_code, item.item_code
						))
				elif packed_item.type == 'Item Group':
					# For item groups, just ensure the group exists in required items
					if packed_item.item_group not in required_items:
						frappe.throw(_("Row #{0}: Item Group {1} is not part of bundle {2}").format(
							item.idx, packed_item.item_group, item.item_code
						))

			# Validate item group quantities
			for req_group, req_data in required_items.items():
				if req_data['type'] == 'Item Group':
					total_qty = sum(flt(item['qty']) for item in req_data['selected_items'])
					if abs(total_qty - req_data['qty']) > 0.0001:
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