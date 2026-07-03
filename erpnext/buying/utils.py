# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import flt, cstr, cint
from frappe import _
import json


def validate_for_items(doc):
	from erpnext.stock.doctype.item.item import validate_end_of_life

	items = []
	for d in doc.get("items"):
		if not d.get("item_coe"):
			continue

		if not d.qty:
			if doc.doctype == "Purchase Receipt" and d.rejected_qty:
				continue
			frappe.throw(_("Please enter quantity for Item {0}").format(d.item_code))

		if not d.get('purchase_order') and not d.get('purchase_receipt'):
			validate_end_of_life(d.item_code)

		# validate stock item
		is_stock_item = frappe.get_cached_value("Item", d.item_code, 'is_stock_item')
		if doc.doctype not in ['Quotation', 'Supplier Quotation']:
			if is_stock_item and d.qty and not d.warehouse and not d.get("delivered_by_supplier"):
				frappe.throw(_("Warehouse is mandatory for stock Item {0} in row {1}").format(d.item_code, d.idx))

		items.append(cstr(d.item_code))

	if not cint(frappe.get_cached_value("Buying Settings", None, "allow_multiple_items") or 0):
		if items and len(items) != len(set(items)):
			frappe.throw(_("Same item cannot be entered multiple times."))


def check_on_hold_or_closed_status(doctype, docname, is_return=False):
	status = frappe.db.get_value(doctype, docname, "status", cache=1)

	if status == "Closed" and not cint(is_return):
		frappe.throw(_("{0} is {1}").format(frappe.get_desk_link(doctype, docname), status), frappe.InvalidStatusError)
	if status in ("On Hold", "Stopped"):
		frappe.throw(_("{0} is {1}").format(frappe.get_desk_link(doctype, docname), status), frappe.InvalidStatusError)


@frappe.whitelist()
def get_linked_material_requests(items):
	items = json.loads(items)
	mr_list = []
	for item in items:
		material_request = frappe.db.sql("""
			SELECT distinct mr.name AS mr_name,
				(mr_item.qty - mr_item.ordered_qty) AS qty,
				mr_item.item_code AS item_code,
				mr_item.name AS mr_item
			FROM `tabMaterial Request` mr, `tabMaterial Request Item` mr_item
			WHERE mr.name = mr_item.parent
				AND mr_item.item_code = %(item)s
				AND mr.material_request_type = 'Purchase'
				AND mr.order_status = 'To Order'
				AND mr.docstatus = 1
				AND mr.status != 'Stopped'
			ORDER BY mr_item.item_code
		""", {"item": item}, as_dict=1)

		if material_request:
			mr_list.append(material_request)

	return mr_list
