# -*- coding: utf-8 -*-
# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from erpnext.stock.utils import get_stock_balance


class QuickStockBalance(Document):
	pass


@frappe.whitelist()
def get_stock_item_details(warehouse, date, item=None, barcode=None):
	out = {}
	if barcode:
		out["item"] = frappe.db.get_value("Item Barcode", filters={"barcode": barcode}, fieldname=["parent"])
		if not out["item"]:
			frappe.throw(_("Invalid Barcode. There is no Item attached to this barcode."))
	else:
		out["item"] = item

	barcodes = frappe.db.get_values("Item Barcode", filters={"parent": out["item"]},
		fieldname=["barcode"])

	stock_balance = get_stock_balance(item_code=out["item"], warehouse=warehouse, posting_date=date, with_valuation_rate=True)

	out["barcodes"] = [x[0] for x in barcodes]
	out["qty"] = stock_balance.qty_after_transaction
	out["value"] = stock_balance.stock_value
	out["image"] = frappe.db.get_value("Item", filters={"name": out["item"]}, fieldname=["image"])
	return out
