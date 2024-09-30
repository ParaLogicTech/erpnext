# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint
from frappe.model.document import Document
from frappe.utils.html_utils import clean_html


class StockSettings(Document):
	def validate(self):
		self.update_global_defaults()
		self.validate_freeze_date()
		self.make_property_setters()
		self.validate_warehouses()
		self.cant_change_valuation_method()
		self.validate_clean_description_html()

		if cint(self.enable_dynamic_bundling):
			make_bundling_fields()

	def update_global_defaults(self):
		global_default_fields = [
			"item_naming_by",
			"item_group",
			"stock_uom",
			"weight_uom",
			"restrict_stock_valuation_to_role",
			"allow_negative_stock",
			"default_warehouse",
			"default_rejected_warehouse",
			"set_qty_in_transactions_based_on_serial_no_input",
		]
		for key in global_default_fields:
			frappe.db.set_default(key, self.get(key, ""))

	def validate_freeze_date(self):
		stock_frozen_limit = 356
		submitted_stock_frozen = self.stock_frozen_upto_days or 0
		if submitted_stock_frozen > stock_frozen_limit:
			self.stock_frozen_upto_days = stock_frozen_limit
			frappe.msgprint(_("`Freeze Stocks Older Than` should be smaller than %d days.") % stock_frozen_limit)

	def make_property_setters(self):
		# show/hide barcode field
		for name in ["scan_barcode"]:
			frappe.make_property_setter({'fieldname': name, 'property': 'hidden',
				'value': 0 if self.show_barcode_field else 1})

		frappe.make_property_setter({'doctype': 'Item', 'fieldname': 'item_naming_by', 'property': 'default',
			'value': self.item_naming_by})

	def validate_warehouses(self):
		warehouse_fields = ["default_warehouse", "sample_retention_warehouse"]
		for field in warehouse_fields:
			if frappe.db.get_value("Warehouse", self.get(field), "is_group"):
				frappe.throw(_("Group Warehouses cannot be used in transactions. Please change the value of {0}") \
					.format(frappe.bold(self.meta.get_field(field).label)), title =_("Incorrect Warehouse"))

	def cant_change_valuation_method(self):
		db_valuation_method = frappe.db.get_single_value("Stock Settings", "valuation_method")

		if db_valuation_method and db_valuation_method != self.valuation_method:
			# check if there are any stock ledger entries against items
			# which does not have it's own valuation method
			sle = frappe.db.sql("""select name from `tabStock Ledger Entry` sle
				where exists(select name from tabItem
					where name=sle.item_code and (valuation_method is null or valuation_method='')) limit 1
			""")

			if sle:
				frappe.throw(_("Can't change valuation method, as there are transactions against some items which does not have it's own valuation method"))

	def validate_clean_description_html(self):
		if int(self.clean_description_html or 0) \
			and not int(self.db_get('clean_description_html') or 0):
			# changed to text
			frappe.enqueue('erpnext.stock.doctype.stock_settings.stock_settings.clean_all_descriptions', now=frappe.flags.in_test)


def clean_all_descriptions():
	for item in frappe.get_all('Item', ['name', 'description']):
		if item.description:
			clean_description = clean_html(item.description)
		if item.description != clean_description:
			frappe.db.set_value('Item', item.name, 'description', clean_description)


def make_bundling_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	df = {
		'label': 'Bundling State',
		'fieldname': 'bundling_state',
		'fieldtype': 'Select',
		'options': "\nStart\nContinue\nTerminate",
		'hidden': 1,
		'report_hide': 1,
		'print_hide': 1,
		'insert_after': 'item_code'
	}

	custom_fields = {
		'Quotation Item': [df],
		'Sales Order Item': [df],
		'Delivery Note Item': [df],
		'Sales Invoice Item': [df],
	}

	create_custom_fields(custom_fields)
