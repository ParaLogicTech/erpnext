# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import getdate
from frappe.model.document import Document


class ItemPriceDuplicateItem(frappe.ValidationError):
	pass


class ItemPrice(Document):
	def validate(self):
		self.validate_dates()
		self.update_price_list_details()
		self.update_item_details()
		self.validate_selling_or_buying()
		self.check_duplicates()

	def validate_selling_or_buying(self):
		if not self.is_new():
			return

		if self.selling:
			self.reference = self.customer
		if self.buying:
			self.reference = self.supplier

		if self.selling and not self.buying:
			self.supplier = None
		if self.buying and not self.selling:
			self.customer = None

	def validate_dates(self):
		if self.valid_from and self.valid_upto:
			if getdate(self.valid_from) > getdate(self.valid_upto):
				frappe.throw(_("Valid From Date must be before Valid Upto Date"))

	def update_price_list_details(self):
		if self.price_list:
			price_list_doc = frappe.get_cached_doc("Price List", self.price_list)
			self.buying = price_list_doc.buying
			self.selling = price_list_doc.selling
			self.currency = price_list_doc.currency

	def update_item_details(self):
		if self.item_code:
			item_doc = frappe.get_cached_doc("Item", self.item_code)
			self.item_name = item_doc.item_name
			self.item_group = item_doc.item_group
			self.brand = item_doc.brand

	def check_duplicates(self):
		filters = {
			"item_code": self.item_code,
			"price_list": self.price_list,
		}

		for field in ("uom", "valid_from", "valid_upto", "customer", "supplier"):
			value = self.get(field)
			if value:
				filters[field] = value
			else:
				filters[field] = ["is", "not set"]

		if not self.is_new():
			filters["name"] = ["!=", self.name]

		existing_item_price = frappe.db.exists("Item Price", filters)
		if existing_item_price:
			frappe.throw(
				_("Item Price appears multiple times based on Item, Price List, Party, UOM and Validity Dates"),
				ItemPriceDuplicateItem,
			)


def on_doctype_update():
	frappe.db.add_index("Item Price", ["item_code", "price_list"])
	frappe.db.add_index("Item Price", ["valid_from", "valid_upto"])
