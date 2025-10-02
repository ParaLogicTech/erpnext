# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import cint
from frappe.model.document import Document


class ProductBundle(Document):
	def autoname(self):
		self.name = self.new_item_code

	def validate(self):
		self.validate_main_item()
		self.validate_child_items()
		from erpnext.utilities.transaction_base import validate_uom_is_integer
		validate_uom_is_integer(self, "uom", "qty")

	def on_update(self):
		self.set_item_is_product_bundle()

	def after_delete(self):
		self.set_item_is_product_bundle()

	def set_item_is_product_bundle(self):
		from erpnext.stock.doctype.packed_item.packed_item import is_product_bundle
		if self.new_item_code:
			new_is_product_bundle = is_product_bundle(self.new_item_code, cache=False)
			old_is_product_bundle = frappe.db.get_value("Item", self.new_item_code, "is_product_bundle")
			if cint(new_is_product_bundle) != cint(old_is_product_bundle):
				frappe.db.set_value("Item", self.new_item_code, "is_product_bundle", cint(new_is_product_bundle), notify=1)

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
