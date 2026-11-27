# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

# import frappe
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document


class SalesPartner(Document):
	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)

	def autoname(self):
		self.name = self.partner_name
