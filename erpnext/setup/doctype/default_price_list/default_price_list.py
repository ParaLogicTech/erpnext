# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class DefaultPriceList(Document):
	pass


def validate_default_price_list_table(doc):
	currencies_visited = set()

	for d in doc.price_lists:
		if not d.default_price_list or not d.currency:
			continue

		if d.currency in currencies_visited:
			frappe.throw(_("Currency {0} is mentioned multiple times in default price list table").format(d.currency))

		currencies_visited.add(d.currency)
