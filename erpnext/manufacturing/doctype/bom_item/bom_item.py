# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

# import frappe
from frappe.utils import cint
from frappe.model.document import Document


class BOMItem(Document):
	@property
	def has_alternative_item(self):
		from erpnext.stock.doctype.item_alternative.item_alternative import has_alternative_item
		return cint(has_alternative_item(self.item_code))
