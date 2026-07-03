# -*- coding: utf-8 -*-
# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PriceListSettings(Document):
	def get_exploded_item_group_order(self, cache=True):
		if cache:
			return frappe.local_cache(
				"get_exploded_item_group_order",
				"",
				self._get_exploded_item_group_order,
			)
		else:
			return self._get_exploded_item_group_order()

	def _get_exploded_item_group_order(self):
		def append_group(parent_item_group, is_child=False):
			if is_child and parent_item_group in item_group_already_defined:
				return

			exploded.append(frappe._dict({"item_group": parent_item_group, "is_exploded": is_child}))
			children = child_group_map.get(parent_item_group) or []
			for child_item_group in children:
				append_group(child_item_group, is_child=True)

		item_group_already_defined = set([d.item_group for d in self.item_group_order])

		all_item_groups = frappe.get_all("Item Group", fields=[
			"name", "is_group", "parent_item_group",
		], order_by="lft")

		child_group_map = {}
		for d in all_item_groups:
			if d.parent_item_group:
				child_group_map.setdefault(d.parent_item_group, []).append(d.name)

		exploded = []
		for d in self.item_group_order:
			append_group(d.item_group)

		for i, d in enumerate(exploded):
			d["idx"] = i + 1

		return exploded
