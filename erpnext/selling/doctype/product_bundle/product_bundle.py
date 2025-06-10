# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ProductBundle(Document):
	def autoname(self):
		self.name = self.new_item_code

	def validate(self):
		self.validate_main_item()
		self.validate_child_items()
		from erpnext.utilities.transaction_base import validate_uom_is_integer
		validate_uom_is_integer(self, "uom", "qty")

	def validate_main_item(self):
		"""Validates, main Item is not a stock item"""
		if frappe.db.get_value("Item", self.new_item_code, "is_stock_item"):
			frappe.throw(_("Parent Item {0} must not be a Stock Item").format(self.new_item_code))

	def validate_child_items(self):
		for item in self.items:
			if item.type == "Item":
				# Clear irrelevant fields
				item.item_group = None
				if frappe.db.exists("Product Bundle", {"new_item_code": item.item_code}):
					frappe.throw(_("Row #{0}: Child Item should not be a Product Bundle. Please remove Item {1} and save").format(
						item.idx, frappe.bold(item.item_code)
					))
					if not item.qty:
						frappe.throw(_("Row #{0}: Quantity is required for type 'Item'").format(item.idx))

			elif item.type == "Item Group":
				item.item_code = None
				item.item_name = None
				item.uom = None
