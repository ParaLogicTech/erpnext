# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from frappe.model.document import Document
from erpnext.stock.doctype.item.item import convert_item_uom_for


class ItemAlternative(Document):
	def validate(self):
		self.validate_alternative_item_allowed()
		self.validate_alternative_item()
		self.validate_duplicate()

	def validate_alternative_item_allowed(self):
		if (
			self.item_code
			and not frappe.db.get_value('Item', self.item_code, 'allow_alternative_item')
		):
			frappe.throw(_("Not allowed to set alternative item for the item {0}").format(self.item_code))

	def validate_alternative_item(self):
		if self.item_code == self.alternative_item_code:
			frappe.throw(_("Alternative Item must not be same as Item Code"))

		item_meta = frappe.get_meta("Item")
		fields = ["is_stock_item", "skip_transfer_for_manufacture", "has_serial_no", "has_batch_no"]
		item_data = frappe.db.get_values("Item", self.item_code, fields, as_dict=1)
		alternative_item_data = frappe.db.get_values("Item", self.alternative_item_code, fields, as_dict=1)

		for field in fields:
			if item_data[0].get(field) != alternative_item_data[0].get(field):
				raise_exception, alert = [1, False] if field == "is_stock_item" else [0, True]

				frappe.msgprint(_("The value of {0} differs between Items {1} and {2}").format(
				frappe.bold(item_meta.get_label(field)),
					frappe.bold(self.alternative_item_code),
					frappe.bold(self.item_code)
				), alert=alert, raise_exception=raise_exception)

	def validate_duplicate(self):
		duplicate = frappe.db.get_value("Item Alternative", {
			'item_code': self.item_code, 'alternative_item_code': self.alternative_item_code, 'name': ('!=', self.name)
		})
		if duplicate:
			frappe.throw(_("Already record exists for the item {0}".format(self.item_code)))


def get_available_alternative_items(original_item_code, warehouse, qty, uom):
	qty = flt(qty)
	if not original_item_code or not warehouse or not qty or not uom:
		return []

	alternative_item_codes = get_alternative_items(original_item_code)
	if not alternative_item_codes:
		return []

	alternative_item_stock_map = dict(frappe.db.sql("""
		select item_code, sum(actual_qty)
		from `tabBin`
		where item_code in %s and warehouse = %s
		group by item_code
	""", (alternative_item_codes, warehouse)))

	available_alternative_items = []
	for alternative_item_code in alternative_item_codes:
		actual_qty = flt(alternative_item_stock_map.get(alternative_item_code))
		converted_actual_qty = convert_item_uom_for(actual_qty, alternative_item_code, to_uom=uom,
			null_if_not_convertible=True) if actual_qty else 0

		if converted_actual_qty and flt(converted_actual_qty, 6) >= flt(qty, 6):
			available_alternative_items.append(alternative_item_code)

	return available_alternative_items


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def alternative_item_query(doctype, txt, searchfield, start, page_len, filters, as_dict=True):
	from erpnext.controllers.queries import item_query

	if not filters:
		filters = {}

	item_code = filters.pop("item_code", None)
	if not item_code:
		return []

	alternative_item_codes = get_alternative_items(item_code)
	if alternative_item_codes:
		filters["name"] = ("in", alternative_item_codes)
	else:
		return []

	return item_query(doctype, txt, searchfield, start, page_len, filters, as_dict=as_dict)


def has_alternative_item(item_code):
	return bool(
		item_code
		and frappe.get_cached_value("Item", item_code, "allow_alternative_item")
		and bool(get_alternative_items(item_code))
	)


def get_alternative_items(item_code):
	if not item_code:
		return []

	def generator():
		alternative_item_codes = frappe.db.sql_list("""
			(
				select alt.alternative_item_code
				from `tabItem Alternative` alt
				inner join `tabItem` im on im.name = alt.alternative_item_code
				where alt.item_code = %(item_code)s and im.disabled = 0
			)
			union
			(
				select alt.item_code
				from `tabItem Alternative` alt
				inner join `tabItem` im on im.name = alt.item_code
				where alt.alternative_item_code = %(item_code)s and alt.two_way = 1 and im.disabled = 0
			)
		""", {"item_code": item_code})

		return list(set(alternative_item_codes))

	return frappe.local_cache("alternative_items", item_code, generator)
