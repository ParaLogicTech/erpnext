# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
import erpnext
from frappe import _, unscrub
from frappe.utils import (
	cint,
	cstr,
	flt,
	formatdate,
	get_timestamp,
	getdate,
	now_datetime,
	random_string,
	get_link_to_form,
	clean_whitespace,
)
from erpnext.controllers.item_variant import (
	ItemVariantExistsError,
	copy_attributes_to_variant,
	get_variant,
	make_variant_item_code,
	validate_item_variant_attributes
)
from erpnext.setup.doctype.uom_conversion_factor.uom_conversion_factor import UOMConversionGraph
from frappe.utils.html_utils import clean_html
from frappe.model.document import Document
import json


class DuplicateReorderRows(frappe.ValidationError):
	pass


class StockExistsForTemplate(frappe.ValidationError):
	pass


class InvalidBarcode(frappe.ValidationError):
	pass


class ConflictingConversionFactors(frappe.ValidationError):
	pass


class Item(Document):
	def get_feed(self):
		return self.get('item_name') or self.get('item_code') or self.get('name')

	def onload(self):
		self.set_onload('stock_exists', self.stock_ledger_created())
		self.set_onload('cant_change_fields', self.get_applicable_cant_change_fields())
		self.set_asset_naming_series()

	@frappe.whitelist()
	def set_asset_naming_series(self):
		if not hasattr(self, '_asset_naming_series'):
			from erpnext.assets.doctype.asset.asset import get_asset_naming_series
			self._asset_naming_series = get_asset_naming_series()

		self.set_onload('asset_naming_series', self._asset_naming_series)

	def autoname(self):
		if self.item_naming_by == "Item Code" and not self.item_code:
			frappe.throw(_("Item Code is mandatory"))

		if self.item_naming_by == "Item Name" and not self.item_name:
			frappe.throw(_("Item Name is mandatory"))

		if self.item_naming_by == "Naming Series":
			if self.variant_of:
				if not self.item_code:
					template_item_name = frappe.db.get_value("Item", self.variant_of, "item_name")
					self.item_code = make_variant_item_code(self.variant_of, template_item_name, self)
			else:
				from frappe.model.naming import set_name_by_naming_series
				set_name_by_naming_series(self)
				self.item_code = self.name
		elif self.item_naming_by == "Item Code":
			self.item_code = clean_whitespace(self.item_code)
			self.name = self.item_code
		elif self.item_naming_by == "Item Name":
			self.validate_item_name()
			self.name = self.item_code = self.item_name

	def before_insert(self):
		self.set_item_override_values()
		self.validate_customer_provided_part()

	def after_insert(self):
		'''set opening stock and item price'''
		if self.standard_rate:
			self.add_price()

	def validate(self):
		self.validate_item_name()
		self.validate_uom()
		self.validate_description()
		self.add_alt_uom_in_conversion_table()
		self.calculate_uom_conversion_factors()
		self.validate_conversion_factor()
		self.validate_item_type()
		self.validate_naming_series()
		self.check_for_active_boms()
		self.fill_customer_code()
		self.validate_barcode()
		self.validate_warehouse_for_reorder()
		self.update_bom_item_desc()

		self.validate_has_variants()
		self.validate_stock_exists_for_template_item()
		self.validate_attributes()
		self.validate_variant_attributes()
		self.validate_variant_based_on_change()
		self.validate_fixed_asset()
		self.validate_retain_sample()
		self.validate_uom_conversion_factor()
		self.validate_weight()
		self.validate_customer_provided_part()
		self.validate_auto_reorder_enabled_in_stock_settings()
		self.validate_applicable_to()
		self.validate_applicable_items()
		self.validate_cant_change()
		self.validate_item_override_values()

	def on_update(self):
		self.validate_name_with_item_group()
		self.update_variants()
		self.update_item_price()
		self.update_serial_no()
		self.update_vehicle()

	def validate_description(self):
		'''Clean HTML description if set'''
		if cint(frappe.db.get_single_value('Stock Settings', 'clean_description_html')):
			self.description = clean_html(self.description)

	def validate_customer_provided_part(self):
		if self.is_customer_provided_item:
			self.is_purchase_item = 0
			self.valuation_rate = 0

			if self.is_sub_contracted_item:
				self.default_material_request_type = "Purchase"
			else:
				self.default_material_request_type = "Customer Provided"

	def add_price(self, price_list=None):
		'''Add a new price'''
		if not price_list:
			price_list = (frappe.db.get_single_value('Selling Settings', 'selling_price_list')
						or frappe.db.get_value('Price List', _('Standard Selling')))
		if price_list:
			item_price = frappe.get_doc({
				"doctype": "Item Price",
				"price_list": price_list,
				"item_code": self.name,
				"currency": erpnext.get_default_currency(),
				"price_list_rate": self.standard_rate,
				"valid_from": None
			})
			item_price.insert()

	def validate_fixed_asset(self):
		if self.is_fixed_asset:
			if self.is_stock_item:
				frappe.throw(_("Fixed Asset Item must be a non-stock item."))

			if not self.asset_category:
				frappe.throw(_("Asset Category is mandatory for Fixed Asset item"))

			if self.stock_ledger_created():
				frappe.throw(_("Cannot be a fixed asset item as Stock Ledger is created."))

		if not self.is_fixed_asset:
			asset = frappe.db.get_all("Asset", filters={"item_code": self.name, "docstatus": 1}, limit=1)
			if asset:
				frappe.throw(_('"Is Fixed Asset" cannot be unchecked, as Asset record exists against the item'))

	def validate_retain_sample(self):
		if self.retain_sample and not frappe.db.get_single_value('Stock Settings', 'sample_retention_warehouse'):
			frappe.throw(_("Please select Sample Retention Warehouse in Stock Settings first"))
		if self.retain_sample and not self.has_batch_no:
			frappe.throw(_(" {0} Retain Sample is based on batch, please check Has Batch No to retain sample of item").format(
				self.item_code))

	def calculate_uom_conversion_factors(self):
		# Get list of all UOMs, stock UOM being index 0
		uoms = [self.stock_uom]
		for d in self.uom_conversion_graph:
			if not d.from_qty:
				frappe.throw(_("Row {0}: UOM Conversion From Qty cannot be 0").format(d.idx))
			if not d.to_qty:
				frappe.throw(_("Row {0}: UOM Conversion To Qty cannot be 0").format(d.idx))
			if d.from_uom == d.to_uom:
				frappe.throw(_("Row {0}: From UOM and To UOM must not be the same").format(d.idx))

			predefined_conv_factor = get_uom_conv_factor(d.from_uom, d.to_uom)
			if predefined_conv_factor:
				input_conv_factor = flt(d.to_qty) / flt(d.from_qty)
				if abs(predefined_conv_factor - input_conv_factor) >= 1.0/10**self.precision("conversion_factor", "uoms"):
					frappe.msgprint("Row {0}: Setting conversion quantities for {1} -> {2} from Global UOM Conversion Factor"
						.format(d.idx, frappe.bold(d.from_uom), frappe.bold(d.to_uom)), alert=True)
					if abs(predefined_conv_factor) >= 1:
						d.from_qty = 1
						d.to_qty = flt(predefined_conv_factor, self.precision("conversion_factor", "uoms"))
					else:
						d.from_qty = flt(1/flt(predefined_conv_factor), self.precision("conversion_factor", "uoms"))
						d.to_qty = 1

			if d.from_uom not in uoms:
				uoms.append(d.from_uom)
			if d.to_uom not in uoms:
				uoms.append(d.to_uom)

		# Create a graph of UOMs
		graph = UOMConversionGraph()
		for d in self.uom_conversion_graph:
			w = flt(d.to_qty) / flt(d.from_qty)
			graph.add_conversion(d.from_uom, d.to_uom, w)

		# Get paths from all UOMs to stock UOM
		uom_conversion_factors = {}
		for from_uom in uoms:
			if from_uom == self.stock_uom:
				continue

			conv = graph.get_conversion_factor(from_uom, self.stock_uom,
				validate_not_convertible=True, validate_multiple_conversion=True, raise_exception=True)
			conv = flt(conv, self.precision("conversion_factor", "uoms"))
			if not conv:
				frappe.throw(_("Conversion factor for UOM {0} is 0").format(from_uom))

			uom_conversion_factors[from_uom] = conv

		# Set Stock UOM's conversion_factor 1
		if self.stock_uom not in uom_conversion_factors:
			uom_conversion_factors[self.stock_uom] = 1.0

		# Only update conversion factors if something has changed
		to_remove = []
		for d in self.uoms:
			if d.uom in uom_conversion_factors:
				d.conversion_factor = uom_conversion_factors[d.uom]
			else:
				to_remove.append(d)

		for d in to_remove:
			self.remove(d)

		existing_uoms = [d.uom for d in self.uoms]
		for from_uom, conversion_factor in uom_conversion_factors.items():
			if from_uom not in existing_uoms:
				self.append('uoms', {'uom': from_uom, 'conversion_factor': conversion_factor})

	def add_alt_uom_in_conversion_table(self):
		uom_conv_list = [(d.from_uom, d.to_uom) for d in self.get("uom_conversion_graph")]
		if self.alt_uom and self.alt_uom != self.stock_uom \
				and (self.stock_uom, self.alt_uom) not in uom_conv_list and (self.alt_uom, self.stock_uom) not in uom_conv_list:
			if not flt(self.alt_uom_size):
				frappe.throw(_("'Per Unit' is invalid"))
			ch = self.append('uom_conversion_graph', {})
			ch.from_qty = 1.0
			ch.from_uom = self.stock_uom
			ch.to_qty = flt(self.alt_uom_size)
			ch.to_uom = self.alt_uom

	def update_template_tables(self):
		template = frappe.get_doc("Item", self.variant_of)

		# copy re-order table if empty
		if not self.get("reorder_levels"):
			for d in template.get("reorder_levels"):
				n = {}
				for k in ("warehouse", "warehouse_reorder_level",
					"warehouse_reorder_qty", "material_request_type"):
					n[k] = d.get(k)
				self.append("reorder_levels", n)

	def validate_conversion_factor(self):
		check_list = []
		for d in self.get('uoms'):
			if cstr(d.uom) in check_list:
				frappe.throw(
					_("Unit of Measure {0} has been entered more than once in Conversion Factor Table").format(d.uom))
			else:
				check_list.append(cstr(d.uom))

			if d.uom and cstr(d.uom) == cstr(self.stock_uom) and flt(d.conversion_factor) != 1:
				frappe.throw(
					_("Conversion factor for default Unit of Measure must be 1"))

			if self.alt_uom and d.uom == self.alt_uom:
				self.alt_uom_size = flt(1/flt(d.conversion_factor), self.precision("alt_uom_size"))

	def validate_item_type(self):
		if self.is_vehicle:
			if not self.is_stock_item:
				frappe.throw(_("'Maintain Stock' must be enabled for Vehicle Item"))
			if not self.has_serial_no:
				self.has_serial_no = 1

		if self.has_serial_no == 1 and self.is_stock_item == 0 and not self.is_fixed_asset:
			frappe.msgprint(_("'Has Serial No' can not be 'Yes' for non-stock item"), raise_exception=1)

		if self.has_serial_no == 0 and self.serial_no_series:
			self.serial_no_series = None

	def validate_naming_series(self):
		for field in ["serial_no_series", "batch_number_series"]:
			series = self.get(field)
			if series and "#" in series and "." not in series:
				frappe.throw(_("Invalid naming series (. missing) for {0}")
					.format(frappe.bold(self.meta.get_field(field).label)))

	def check_for_active_boms(self):
		if self.default_bom:
			bom_item = frappe.db.get_value("BOM", self.default_bom, "item")
			if bom_item not in (self.name, self.variant_of):
				frappe.throw(
					_("Default BOM ({0}) must be active for this item or its template").format(bom_item))

	def fill_customer_code(self):
		""" Append all the customer codes and insert into "customer_code" field of item table """
		cust_code = []
		for d in self.get('customer_items'):
			cust_code.append(d.ref_code)
		self.customer_code = ','.join(cust_code)

	def validate_item_name(self):
		if not self.item_name:
			self.item_name = self.item_code

		self.item_name = clean_whitespace(self.item_name)

	def validate_barcode(self):
		from stdnum import ean
		if len(self.barcodes) > 0:
			for item_barcode in self.barcodes:
				options = frappe.get_meta("Item Barcode").get_options("barcode_type").split('\n')
				if item_barcode.barcode:
					duplicate = frappe.db.sql(
						"""select parent from `tabItem Barcode` where barcode = %s and parent != %s""", (item_barcode.barcode, self.name))
					if duplicate:
						frappe.throw(_("Barcode {0} already used in Item {1}").format(
							item_barcode.barcode, duplicate[0][0]))

					item_barcode.barcode_type = "" if item_barcode.barcode_type not in options else item_barcode.barcode_type
					if item_barcode.barcode_type and item_barcode.barcode_type.upper() in ('EAN', 'UPC-A', 'EAN-13', 'EAN-8'):
						if not ean.is_valid(item_barcode.barcode):
							frappe.throw(_("Barcode {0} is not a valid {1} code").format(
								item_barcode.barcode, item_barcode.barcode_type), InvalidBarcode)

					if item_barcode.barcode != item_barcode.name:
						# if barcode is getting updated , the row name has to reset.
						# Delete previous old row doc and re-enter row as if new to reset name in db.
						item_barcode.set("__islocal", True)
						item_barcode.name = None
						frappe.delete_doc("Item Barcode", item_barcode.name)

	def validate_warehouse_for_reorder(self):
		'''Validate Reorder level table for duplicate and conditional mandatory'''
		warehouse = []
		for d in self.get("reorder_levels"):
			if not d.warehouse_group:
				d.warehouse_group = d.warehouse
			if d.get("warehouse") and d.get("warehouse") not in warehouse:
				warehouse += [d.get("warehouse")]
			else:
				frappe.throw(_("Row {0}: An Reorder entry already exists for this warehouse {1}")
									.format(d.idx, d.warehouse), DuplicateReorderRows)

			if d.warehouse_reorder_level and not d.warehouse_reorder_qty:
				frappe.throw(_("Row #{0}: Please set reorder quantity").format(d.idx))

	def stock_ledger_created(self):
		if not hasattr(self, '_stock_ledger_created'):
			self._stock_ledger_created = len(frappe.db.sql("""select name from `tabStock Ledger Entry`
				where item_code = %s limit 1""", self.name))
		return self._stock_ledger_created

	def validate_name_with_item_group(self):
		# causes problem with tree build
		if frappe.db.exists("Item Group", self.name):
			frappe.throw(
				_("An Item Group exists with same name, please change the item name or rename the item group"))

	def update_item_price(self):
		frappe.db.sql("""
			update `tabItem Price` set item_name=%s, item_description=%s, item_group=%s, brand=%s
			where item_code=%s
		""", (self.item_name, self.description, self.item_group, self.brand, self.name))

	def update_serial_no(self):
		if self.has_serial_no:
			frappe.db.sql("update `tabSerial No` set item_name=%s, item_group=%s, brand=%s where item_code=%s",
				(self.item_name, self.item_group, self.brand, self.name))

	def update_vehicle(self):
		if self.is_vehicle:
			frappe.db.sql("update `tabVehicle` set item_name=%s, item_group=%s, brand=%s where item_code=%s",
				(self.item_name, self.item_group, self.brand, self.name))

			if self.image:
				frappe.db.sql("update `tabVehicle` set image=%s where item_code=%s and image = '' or image is null",
					(self.image, self.name))

	def on_trash(self):
		frappe.db.sql("""delete from tabBin where item_code=%s""", self.name)
		frappe.db.sql("delete from `tabItem Price` where item_code=%s", self.name)
		for variant_of in frappe.get_all("Item", filters={"variant_of": self.name}):
			frappe.delete_doc("Item", variant_of.name)

	def before_rename(self, old_name, new_name, merge=False):
		if self.item_name == old_name and self.item_naming_by == "Item Name":
			frappe.db.set_value("Item", old_name, "item_name", new_name)

		if merge:
			# Validate properties before merging
			if not frappe.db.exists("Item", new_name):
				frappe.throw(_("Item {0} does not exist").format(new_name))

			new_properties = [cstr(d) for d in frappe.db.get_value("Item", new_name, self.get_cant_change_fields())]
			if new_properties != [cstr(self.get(fld)) for fld in self.get_cant_change_fields()]:
				frappe.throw(_("To merge, following properties must be same for both items")
									+ ": \n" + ", ".join([self.meta.get_label(fld) for fld in self.get_cant_change_fields()]))

	def after_rename(self, old_name, new_name, merge):
		if merge:
			self.validate_duplicate_item_in_stock_reconciliation(old_name, new_name)

		frappe.db.set_value("Item", new_name, "item_code", new_name)

		if merge:
			self.set_last_purchase_rate(new_name)
			self.recalculate_bin_qty(new_name)

		for dt in ("Sales Taxes and Charges", "Purchase Taxes and Charges"):
			for d in frappe.db.sql("""select name, item_wise_tax_detail from `tab{0}`
					where ifnull(item_wise_tax_detail, '') != ''""".format(dt), as_dict=1):

				item_wise_tax_detail = json.loads(d.item_wise_tax_detail)
				if isinstance(item_wise_tax_detail, dict) and old_name in item_wise_tax_detail:
					item_wise_tax_detail[new_name] = item_wise_tax_detail[old_name]
					item_wise_tax_detail.pop(old_name)

					frappe.db.set_value(dt, d.name, "item_wise_tax_detail",
											json.dumps(item_wise_tax_detail), update_modified=False)

	def validate_duplicate_item_in_stock_reconciliation(self, old_name, new_name):
		records = frappe.db.sql(""" SELECT parent, COUNT(*) as records
			FROM `tabStock Reconciliation Item`
			WHERE item_code = %s and docstatus = 1
			GROUP By item_code, warehouse, parent
			HAVING records > 1
		""", new_name, as_dict=1)

		if not records: return
		document = _("Stock Reconciliation") if len(records) == 1 else _("Stock Reconciliations")

		msg = _("The items {0} and {1} are present in the following {2} : <br>"
			.format(frappe.bold(old_name), frappe.bold(new_name), document))

		msg += ', '.join([get_link_to_form("Stock Reconciliation", d.parent) for d in records]) + "<br><br>"

		msg += _("Note: To merge the items, create a separate Stock Reconciliation for the old item {0}"
			.format(frappe.bold(old_name)))

		frappe.throw(_(msg), title=_("Merge not allowed"))

	def set_last_purchase_rate(self, new_name):
		last_purchase_rate = get_last_purchase_details(new_name).get("base_net_rate", 0)
		frappe.db.set_value("Item", new_name, "last_purchase_rate", last_purchase_rate)

	def recalculate_bin_qty(self, new_name):
		from erpnext.stock.stock_balance import repost_stock
		#frappe.db.auto_commit_on_many_writes = 1
		#existing_allow_negative_stock = frappe.db.get_value("Stock Settings", None, "allow_negative_stock")
		#frappe.db.set_value("Stock Settings", None, "allow_negative_stock", 1)

		repost_stock_for_warehouses = frappe.db.sql_list("""select distinct warehouse
			from tabBin where item_code=%s""", new_name)

		# Delete all existing bins to avoid duplicate bins for the same item and warehouse
		frappe.db.sql("delete from `tabBin` where item_code=%s", new_name)

		for warehouse in repost_stock_for_warehouses:
			repost_stock(new_name, warehouse)

		#frappe.db.set_value("Stock Settings", None, "allow_negative_stock", existing_allow_negative_stock)
		#frappe.db.auto_commit_on_many_writes = 0

	def update_bom_item_desc(self):
		if self.is_new():
			return

		if self.db_get('description') != self.description:
			frappe.db.sql("""
				update `tabBOM`
				set description = %s
				where item = %s and docstatus < 2
			""", (self.description, self.name))

			frappe.db.sql("""
				update `tabBOM Item`
				set description = %s
				where item_code = %s and docstatus < 2
			""", (self.description, self.name))

			frappe.db.sql("""
				update `tabBOM Explosion Item`
				set description = %s
				where item_code = %s and docstatus < 2
			""", (self.description, self.name))

	def update_variants(self):
		if self.flags.dont_update_variants or \
						frappe.db.get_single_value('Item Variant Settings', 'do_not_update_variants'):
			return
		if self.has_variants:
			variants = frappe.db.get_all("Item", fields=["item_code"], filters={"variant_of": self.name})
			if variants:
				if len(variants) <= 30:
					update_variants(variants, self, publish_progress=False)
					frappe.msgprint(_("Item Variants updated"))
				else:
					frappe.enqueue("erpnext.stock.doctype.item.item.update_variants",
						variants=variants, template=self, now=frappe.flags.in_test, timeout=600)

	def validate_has_variants(self):
		if not self.has_variants and frappe.db.get_value("Item", self.name, "has_variants"):
			if frappe.db.exists("Item", {"variant_of": self.name}):
				frappe.throw(_("Item has variants."))

	def validate_stock_exists_for_template_item(self):
		if self.stock_ledger_created() and self.get('_doc_before_save'):
			if (cint(self._doc_before_save.has_variants) != cint(self.has_variants)
				or self._doc_before_save.variant_of != self.variant_of):
				frappe.throw(_("Cannot change Variant properties after stock transaction. You will have to make a new Item to do this.").format(self.name),
					StockExistsForTemplate)

			if self.has_variants or self.variant_of:
				if not self.is_child_table_same('attributes'):
					frappe.throw(
						_('Cannot change Attributes after stock transaction. Make a new Item and transfer stock to the new Item'))

	def validate_variant_based_on_change(self):
		if not self.is_new() and (self.variant_of or (self.has_variants and frappe.get_all("Item", {"variant_of": self.name}))):
			if self.variant_based_on != frappe.db.get_value("Item", self.name, "variant_based_on"):
				frappe.throw(_("Variant Based On cannot be changed"))

	def validate_uom(self):
		if not self.is_new():
			check_stock_uom_with_bin(self.name, self.stock_uom)
		if self.has_variants:
			for d in frappe.db.get_all("Item", filters={"variant_of": self.name}):
				check_stock_uom_with_bin(d.name, self.stock_uom)
		if self.variant_of:
			template_uom = frappe.db.get_value("Item", self.variant_of, "stock_uom")
			if template_uom != self.stock_uom:
				frappe.throw(_("Default Unit of Measure for Variant '{0}' must be same as in Template '{1}'").format(
					self.stock_uom, template_uom
				))

		if self.alt_uom == self.stock_uom:
			self.alt_uom = ""
		if not self.alt_uom:
			self.alt_uom_size = 1

	def validate_uom_conversion_factor(self):
		if self.uoms:
			for d in self.uoms:
				value = get_uom_conv_factor(d.uom, self.stock_uom)
				if value and abs(value - d.conversion_factor) >= 1.0/10**self.precision("conversion_factor", "uoms"):
					frappe.msgprint("Setting conversion factor for UOM {0} from UOM Conversion Factor Master as {1}"
						.format(d.uom, value), alert=True)
					d.conversion_factor = value

	def validate_weight(self):
		weight_fields = ["net_weight_per_unit", "tare_weight_per_unit", "gross_weight_per_unit"]
		self.round_floats_in(self, weight_fields)

		if self.is_packaging_material:
			self.net_weight_per_unit = 0
			self.gross_weight_per_unit = self.tare_weight_per_unit
		else:
			if self.net_weight_per_unit and self.gross_weight_per_unit and not self.tare_weight_per_unit:
				self.tare_weight_per_unit = flt(self.gross_weight_per_unit - self.net_weight_per_unit,
					self.precision("tare_weight_per_unit"))

			if self.gross_weight_per_unit and self.tare_weight_per_unit and not self.net_weight_per_unit:
				self.net_weight_per_unit = flt(flt(self.gross_weight_per_unit) - flt(self.tare_weight_per_unit),
					self.precision("net_weight_per_unit"))

			if flt(self.net_weight_per_unit):
				self.gross_weight_per_unit = flt(self.net_weight_per_unit + self.tare_weight_per_unit,
					self.precision("gross_weight_per_unit"))

		for weight_field in weight_fields:
			weight_label = self.meta.get_label(weight_field)

			if flt(self.get(weight_field)) < 0:
				frappe.throw(_("{0} cannot be negative").format(frappe.bold(weight_label)))

			if not self.weight_uom and flt(self.get(weight_field)):
				frappe.throw(_("Please set Weight UOM for '{0}'").format(weight_label))

	def validate_attributes(self):
		if not (self.has_variants or self.variant_of):
			return

		if not self.variant_based_on:
			self.variant_based_on = 'Item Attribute'

		if self.variant_based_on == 'Item Attribute':
			attributes = []
			if not self.attributes:
				frappe.throw(_("Attribute table is mandatory"))
			for d in self.attributes:
				if d.attribute in attributes:
					frappe.throw(
						_("Attribute {0} selected multiple times in Attributes Table".format(d.attribute)))
				else:
					attributes.append(d.attribute)

	def validate_variant_attributes(self):
		if self.is_new() and self.variant_of and self.variant_based_on == 'Item Attribute':
			# remove attributes with no attribute_value set
			self.attributes = [d for d in self.attributes if cstr(d.attribute_value).strip()]

			args = {}
			for i, d in enumerate(self.attributes):
				d.idx = i + 1
				args[d.attribute] = d.attribute_value

			variant = get_variant(self.variant_of, args, self.name)
			if variant:
				frappe.throw(_("Item variant {0} exists with same attributes")
					.format(variant), ItemVariantExistsError)

			validate_item_variant_attributes(self, args)

			# copy variant_of value for each attribute row
			for d in self.attributes:
				d.variant_of = self.variant_of

	def get_cant_change_fields(self):
		return (
			self.get_cant_change_fields_based_on_bin()
			+ self.get_cant_change_fields_based_on_sle()
			+ self.get_cant_change_fields_based_on_transactions()
		)

	def get_cant_change_fields_based_on_bin(self):
		return ["is_stock_item"]

	def get_cant_change_fields_based_on_sle(self):
		return ["has_serial_no", "has_batch_no", "valuation_method", "is_vehicle"]

	def get_cant_change_fields_based_on_transactions(self):
		return ["stock_uom", "alt_uom", "alt_uom_size", "is_vehicle"]

	def get_applicable_cant_change_fields(self):
		fieldnames = []

		if not self.is_new():
			for fieldname in self.get_cant_change_fields():
				if self.check_if_cant_change_field(fieldname):
					fieldnames.append(fieldname)

		return fieldnames

	def validate_cant_change(self):
		from frappe.model import numeric_fieldtypes

		def has_changed(fieldname):
			number_comparison = False
			if self.meta.get_field(fieldname).fieldtype in numeric_fieldtypes:
				number_comparison = True

			if number_comparison:
				return flt(self.get(field)) != flt(before_save_values.get(field))
			else:
				return self.get(field) != before_save_values.get(field)

		if not self.is_new():
			before_save_values = frappe.db.get_value("Item", self.name, self.get_cant_change_fields(), as_dict=True)
			if not before_save_values.get('valuation_method') and self.get('valuation_method'):
				before_save_values['valuation_method'] = frappe.db.get_single_value("Stock Settings", "valuation_method") or "FIFO"

			if before_save_values:
				for field in self.get_cant_change_fields():
					if has_changed(field) and not self.flags.get('force_allow_change', {}).get(field) and self.check_if_cant_change_field(field):
						frappe.throw(_("As there are existing transactions against item {0}, you can not change the value of {1}")
							.format(self.name, frappe.bold(self.meta.get_label(field))))

	def check_if_cant_change_field(self, field):
		link_doctypes_bin = ["Sales Order Item", "Purchase Order Item", "Material Request Item", "Work Order"]
		linked_doctypes = [
			"Delivery Note Item", "Sales Invoice Item",
			"Purchase Receipt Item", "Purchase Invoice Item",
			"Stock Entry Detail", "Stock Reconciliation Item"
		] + link_doctypes_bin
		linked_doctypes_vehicle = ["Vehicle Allocation", "Vehicle Booking Order"]

		if field in self.get_cant_change_fields_based_on_sle() or field in self.get_cant_change_fields_based_on_bin():
			if self.stock_ledger_created():
				return True

		if field in self.get_cant_change_fields_based_on_bin():
			for doctype in link_doctypes_bin:
				if self.check_if_linked_doctype_exists(doctype):
					return True

		if field in self.get_cant_change_fields_based_on_transactions():
			for doctype in linked_doctypes:
				if self.check_if_linked_doctype_exists(doctype):
					return True

		if field == 'is_vehicle':
			for doctype in linked_doctypes_vehicle:
				if self.check_if_linked_doctype_exists(doctype):
					return True

	def set_item_override_values(self):
		override_values = get_item_override_values(self.as_dict())['values']
		self.update(override_values)

	def validate_item_override_values(self):
		get_item_override_values(self.as_dict(), validate=True)

	def check_if_linked_doctype_exists(self, doctype, fieldname=None):
		if not hasattr(self, "_linked_doctype_exists"):
			self._linked_doctype_exists = {}

		if doctype in self._linked_doctype_exists:
			return self._linked_doctype_exists[doctype]

		if not fieldname:
			fieldname = "production_item" if doctype == "Work Order" else "item_code"

		self._linked_doctype_exists[doctype] = frappe.db.get_value(doctype, filters={fieldname: self.name, "docstatus": 1})
		return self._linked_doctype_exists[doctype]

	def validate_auto_reorder_enabled_in_stock_settings(self):
		if self.reorder_levels:
			enabled = frappe.db.get_single_value('Stock Settings', 'auto_indent')
			if not enabled:
				frappe.msgprint(msg=_("You have to enable auto re-order in Stock Settings to maintain re-order levels."), title=_("Enable Auto Re-Order"), indicator="orange")

	def validate_applicable_to(self):
		for d in self.applicable_to:
			if d.applicable_to_item == self.name:
				frappe.throw(_("Row #{0}: Applicable To Item cannot be the same as this Item").format(d.idx))

	def validate_applicable_items(self):
		visited = set()
		for d in self.applicable_items:
			if d.applicable_item_code:
				if d.applicable_item_code == self.name:
					frappe.throw(_("Row #{0}: Applicable Item cannot be the same as this Item").format(d.idx))

				if d.applicable_item_code in visited:
					frappe.throw(_("Row #{0}: Duplicate Applicable Item {1}")
						.format(d.idx, frappe.bold(d.applicable_item_code)))

				visited.add(cstr(d.applicable_item_code))


def get_timeline_data(doctype, name):
	'''returns timeline data based on stock ledger entry'''
	out = {}
	items = dict(frappe.db.sql('''select posting_date, count(*)
		from `tabStock Ledger Entry` where item_code=%s
			and posting_date > date_sub(curdate(), interval 1 year)
			group by posting_date''', name))

	for date, count in items.items():
		timestamp = get_timestamp(date)
		out.update({timestamp: count})

	return out


def validate_end_of_life(item_code, end_of_life=None, disabled=None, verbose=1):
	if (not end_of_life) or (disabled is None):
		end_of_life, disabled = frappe.get_cached_value("Item", item_code, ["end_of_life", "disabled"])

	if end_of_life and end_of_life != "0000-00-00" and getdate(end_of_life) <= now_datetime().date():
		msg = _("Item {0} has reached its end of life on {1}").format(frappe.bold(item_code), formatdate(end_of_life))
		_msgprint(msg, verbose)

	if disabled:
		_msgprint(_("Item {0} is disabled").format(frappe.bold(item_code)), verbose)


def validate_is_stock_item(item_code, is_stock_item=None, verbose=1):
	if not is_stock_item:
		is_stock_item = frappe.get_cached_value("Item", item_code, "is_stock_item")

	if is_stock_item != 1:
		msg = _("Item {0} is not a stock Item").format(item_code)

		_msgprint(msg, verbose)


def validate_cancelled_item(item_code, docstatus=None, verbose=1):
	if docstatus is None:
		docstatus = frappe.db.get_value("Item", item_code, "docstatus")

	if docstatus == 2:
		msg = _("Item {0} is cancelled").format(item_code)
		_msgprint(msg, verbose)


def _msgprint(msg, verbose):
	if verbose:
		frappe.msgprint(msg, raise_exception=True)
	else:
		raise frappe.ValidationError(msg)


def get_last_purchase_details(item_code, doc_name=None, conversion_rate=1.0, transaction_date=None):
	"""returns last purchase details in stock uom"""
	# get last purchase order item details

	po_date_condition = ""
	prec_date_condition = ""
	if transaction_date:
		transaction_date = getdate(transaction_date)
		po_date_condition = " and po.transaction_date <= '{0}'".format(transaction_date)
		prec_date_condition = " and pr.posting_time <= '{0}'".format(transaction_date)

	last_purchase_order = frappe.db.sql("""
		select po.name, po.transaction_date, po.conversion_rate,
			po_item.conversion_factor, po_item.base_price_list_rate,
			po_item.discount_percentage, po_item.base_rate, po_item.base_net_rate
		from `tabPurchase Order` po, `tabPurchase Order Item` po_item
		where po.docstatus = 1 and po_item.item_code = %s and po.name != %s and
			po.name = po_item.parent {0}
		order by po.transaction_date desc, po.name desc
		limit 1""".format(po_date_condition), (item_code, cstr(doc_name)), as_dict=1)

	# get last purchase receipt item details
	last_purchase_receipt = frappe.db.sql("""
		select pr.name, pr.posting_date, pr.posting_time, pr.conversion_rate,
			pr_item.conversion_factor, pr_item.base_price_list_rate, pr_item.discount_percentage,
			pr_item.base_rate, pr_item.base_net_rate
		from `tabPurchase Receipt` pr, `tabPurchase Receipt Item` pr_item
		where pr.docstatus = 1 and pr_item.item_code = %s and pr.name != %s and
			pr.name = pr_item.parent {0}
		order by pr.posting_date desc, pr.posting_time desc, pr.name desc
		limit 1""".format(prec_date_condition), (item_code, cstr(doc_name)), as_dict=1)

	purchase_order_date = getdate(last_purchase_order and last_purchase_order[0].transaction_date
							   or "1900-01-01")
	purchase_receipt_date = getdate(last_purchase_receipt and
								 last_purchase_receipt[0].posting_date or "1900-01-01")

	if last_purchase_order and (purchase_order_date >= purchase_receipt_date or not last_purchase_receipt):
		# use purchase order
		
		last_purchase = last_purchase_order[0]
		purchase_date = purchase_order_date

	elif last_purchase_receipt and (purchase_receipt_date > purchase_order_date or not last_purchase_order):
		# use purchase receipt
		last_purchase = last_purchase_receipt[0]
		purchase_date = purchase_receipt_date

	else:
		return frappe._dict()

	conversion_factor = flt(last_purchase.conversion_factor)
	out = frappe._dict({
		"base_price_list_rate": flt(last_purchase.base_price_list_rate) / conversion_factor,
		"base_rate": flt(last_purchase.base_rate) / conversion_factor,
		"base_net_rate": flt(last_purchase.base_net_rate) / conversion_factor,
		"discount_percentage": flt(last_purchase.discount_percentage),
		"purchase_date": purchase_date
	})

	conversion_rate = flt(conversion_rate) or 1.0
	out.update({
		"price_list_rate": out.base_price_list_rate / conversion_rate,
		"rate": out.base_rate / conversion_rate,
		"base_rate": out.base_rate,
		"base_net_rate": out.base_net_rate
	})

	return out


def check_stock_uom_with_bin(item, stock_uom):
	if stock_uom == frappe.db.get_value("Item", item, "stock_uom"):
		return

	matched = True
	ref_uom = frappe.db.get_value("Stock Ledger Entry", {"item_code": item}, "stock_uom")

	if ref_uom:
		if cstr(ref_uom) != cstr(stock_uom):
			matched = False
	else:
		bin_list = frappe.db.sql("select * from tabBin where item_code=%s", item, as_dict=1)
		for bin in bin_list:
			if (bin.reserved_qty > 0 or bin.ordered_qty > 0 or bin.indented_qty > 0
								or bin.planned_qty > 0) and cstr(bin.stock_uom) != cstr(stock_uom):
				matched = False
				break

		if matched and bin_list:
			frappe.db.sql("""update tabBin set stock_uom=%s where item_code=%s""", (stock_uom, item))

	if not matched:
		frappe.throw(
			_("Default Unit of Measure for Item {0} cannot be changed directly because you have already made some transaction(s) with another UOM. You will need to create a new Item to use a different Default UOM.").format(item))


@frappe.whitelist()
def get_uom_conv_factor(from_uom, to_uom):
	from erpnext.setup.doctype.uom_conversion_factor.uom_conversion_factor import get_uom_conv_factor
	return get_uom_conv_factor(from_uom, to_uom)


def get_convertible_item_uoms(item_code):
	from erpnext.setup.doctype.uom_conversion_factor.uom_conversion_factor import get_conversion_map

	item = frappe.get_cached_doc("Item", item_code)
	conversion_map = get_conversion_map()

	convertible_uoms = []
	for d in item.uoms:
		convertible_uoms.append(d.uom)
		for connected_uom in conversion_map.get(d.uom, {}):
			convertible_uoms.append(connected_uom)

	convertible_uoms = list(set(convertible_uoms))
	return convertible_uoms


@frappe.whitelist()
def convert_item_uom_for(value, item_code, from_uom=None, to_uom=None, conversion_factor=None,
		null_if_not_convertible=False, is_rate=False):
	from erpnext.stock.get_item_details import get_conversion_factor

	value = flt(value)
	conversion_factor = flt(conversion_factor)

	if cstr(from_uom) != cstr(to_uom):
		# From UOM to Stock UOM
		from_uom = from_uom or frappe.get_cached_value("Item", item_code, 'stock_uom')

		from_stock_uom_conversion = get_conversion_factor(item_code, from_uom)
		if from_stock_uom_conversion.get('not_convertible') and null_if_not_convertible:
			return None

		if is_rate:
			value /= flt(from_stock_uom_conversion.get('conversion_factor'))
		else:
			value *= flt(from_stock_uom_conversion.get('conversion_factor'))

		# Stock UOM to To UOM
		if conversion_factor:
			if is_rate:
				value *= conversion_factor
			else:
				value /= conversion_factor
		else:
			to_uom_conversion = get_conversion_factor(item_code, to_uom)
			if to_uom_conversion.get('not_convertible') and null_if_not_convertible:
				return None

			if is_rate:
				value *= flt(to_uom_conversion.get('conversion_factor'))
			else:
				value /= flt(to_uom_conversion.get('conversion_factor'))

	return value


@frappe.whitelist()
def get_item_attribute(parent, attribute_value=''):
	if not frappe.has_permission("Item"):
		frappe.msgprint(_("No Permission"), raise_exception=1)

	return frappe.get_all("Item Attribute Value", fields=["attribute_value"],
		filters={'parent': parent, 'attribute_value': ("like", "%%%s%%" % attribute_value)})


@frappe.whitelist()
def get_item_override_values(args, validate=False):
	if isinstance(args, str):
		args = json.loads(args)

	args = frappe._dict(args)

	override_values = frappe._dict()
	item_fields = {
		'item_naming_by': 'Data',
		'naming_series': 'Data',
		'stock_uom': 'Data',
		'is_stock_item': 'YesNo',
		'is_fixed_asset': 'YesNo',
		'has_serial_no': 'YesNo',
		'has_batch_no': 'YesNo',
		'is_vehicle': 'YesNo',
		'has_variants': 'YesNo',
		'is_sales_item': 'YesNo',
		'is_purchase_item': 'YesNo',
		'is_packaging_material': 'YesNo',
		'is_customer_provided_item': 'YesNo',
	}

	hooks = frappe.get_hooks('update_item_override_fields')
	for method in hooks:
		frappe.get_attr(method)(item_fields, args, validate)

	def throw_override_must_be(doc, target_fieldname, source_value):
		df = frappe.get_meta("Item").get_field(target_fieldname)
		if df:
			label = _(df.label)
		else:
			label = _(unscrub(target_fieldname))

		frappe.throw(_("Items of {0} {1} must have {2} set as '{3}'")
			.format(doc.doctype, doc.name, frappe.bold(label), frappe.bold(source_value)))

	def set_override_values(doc):
		for target_fieldname, fieldtype in item_fields.items():
			if target_fieldname not in override_values:
				source_fieldname = target_fieldname
				if target_fieldname == 'naming_series':
					source_fieldname = 'item_naming_series'

				if args.variant_of and target_fieldname == "has_variants":
					continue

				source_value = doc.get(source_fieldname)
				if source_value:
					target_value = source_value
					if fieldtype == 'YesNo':
						target_value = cint(source_value == 'Yes')

					if validate and target_value != args.get(target_fieldname):
						throw_override_must_be(doc, target_fieldname, source_value)

					override_values[target_fieldname] = target_value

	if args.brand:
		brand = frappe.get_cached_doc("Brand", args.brand)
		set_override_values(brand)

	current_item_group_name = args.item_group
	while current_item_group_name:
		item_group = frappe.get_cached_doc("Item Group", current_item_group_name)
		set_override_values(item_group)
		current_item_group_name = item_group.parent_item_group

	if args.item_source:
		item_source = frappe.get_cached_doc("Item Source", args.item_source)
		set_override_values(item_source)

	if override_values.naming_series and override_values.item_naming_by != 'Naming Series':
		del override_values['naming_series']
	if override_values.has_variants and args.variant_of:
		del override_values['has_variants']

	return {
		'fieldnames': list(item_fields.keys()),
		'values': override_values
	}


@frappe.whitelist()
def change_uom(item_code, stock_uom=None, alt_uom=None, alt_uom_size=None):
	item = frappe.get_doc("Item", item_code)
	item.check_permission('write')

	alt_uom_size = flt(alt_uom_size, item.precision('alt_uom_size'))
	alt_uom = cstr(alt_uom)

	change_stock_uom = stock_uom and stock_uom != item.stock_uom
	change_alt_uom = alt_uom != item.alt_uom
	change_alt_uom_size = (alt_uom or item.alt_uom) and alt_uom_size and alt_uom_size != flt(item.alt_uom_size, item.precision('alt_uom_size'))

	if not change_stock_uom and not change_alt_uom and not change_alt_uom_size:
		frappe.throw(_("Nothing to change"))

	one_uom_dts = [
		'Bin', 'Stock Ledger Entry',
		'Product Bundle Item', 'Packed Item',
		'Purchase Receipt Item Supplied', 'Purchase Order Item Supplied',
		'Item Price', 'Pricing Rule Item Code',
		'Production Plan Item', 'Job Card Item', 'BOM', 'BOM Scrap Item', 'BOM Explosion Item', 'Work Order',
		'Material Request Plan Item'
	]
	two_uom_dts = [
		'Pick List Item', 'Request for Quotation Item', 'BOM Item',
		'Packing Slip Item', 'Packing Slip Packaging Material', 'Package Type Packaging Material'
	]
	three_uom_dts = [
		'Quotation Item', 'Sales Order Item', 'Delivery Note Item', 'Sales Invoice Item',
		'Supplier Quotation Item', 'Purchase Order Item', 'Purchase Receipt Item', 'Purchase Invoice Item',
		'Stock Entry Detail', 'Material Request Item'
	]

	all_dts = one_uom_dts + two_uom_dts + three_uom_dts

	args = {
		'item_code': item_code,
		'stock_uom': stock_uom, 'old_stock_uom': item.stock_uom,
		'alt_uom': alt_uom, 'alt_uom_size': alt_uom_size,
		'modified': frappe.utils.now(), 'user': frappe.session.user
	}

	non_standard_item_field = {
		"Purchase Receipt Item Supplied": "rm_item_code",
		"Purchase Order Item Supplied": "rm_item_code",
		"Work Order": "production_item",
		"BOM": "item"
	}

	for dt in all_dts:
		item_field = non_standard_item_field.get(dt) or 'item_code'

		if change_stock_uom and frappe.get_meta(dt).has_field('stock_uom'):
			frappe.db.sql("""
				update `tab{0}`
				set stock_uom = %(stock_uom)s, modified = %(modified)s, modified_by = %(user)s
				where {1} = %(item_code)s
			""".format(dt, item_field), args)

		if change_stock_uom and frappe.get_meta(dt).has_field('uom'):
			frappe.db.sql("""
				update `tab{0}`
				set uom = %(stock_uom)s, modified = %(modified)s, modified_by = %(user)s
				where {1} = %(item_code)s and uom = %(old_stock_uom)s
			""".format(dt, item_field), args)

		if change_alt_uom and frappe.get_meta(dt).has_field('alt_uom'):
			frappe.db.sql("""
				update `tab{0}`
				set alt_uom = %(alt_uom)s, modified = %(modified)s, modified_by = %(user)s
				where {1} = %(item_code)s
			""".format(dt, item_field), args)

	def get_uom_rows_to_update(old_uom, new_uom):
		if new_uom:
			from_uoms = [(d, 'from_uom', new_uom) for d in item.uom_conversion_graph if d.from_uom == old_uom]
			to_uoms = [(d, 'to_uom', new_uom) for d in item.uom_conversion_graph if d.to_uom == old_uom]
			return from_uoms + to_uoms
		else:
			return []

	uom_rows_to_update = []
	if change_stock_uom:
		uom_rows_to_update += get_uom_rows_to_update(item.stock_uom, stock_uom)
	if change_alt_uom:
		uom_rows_to_update += get_uom_rows_to_update(item.alt_uom, alt_uom)

	for d, fieldname, value in uom_rows_to_update:
		d.set(fieldname, value)

	if change_stock_uom:
		item.stock_uom = stock_uom
	if change_alt_uom:
		item.alt_uom = alt_uom

	if change_alt_uom_size:
		uom_conversion_row = [d for d in item.uom_conversion_graph if {d.from_uom, d.to_uom} == {item.stock_uom, item.alt_uom}]
		for d in uom_conversion_row:
			d.from_qty = 1.0
			d.from_uom = item.stock_uom
			d.to_qty = alt_uom_size
			d.to_uom = item.alt_uom

		item.alt_uom_size = alt_uom_size

	item.flags.force_allow_change = {
		"stock_uom": change_stock_uom,
		"alt_uom": change_alt_uom,
		"alt_uom_size": change_alt_uom or change_alt_uom_size
	}
	item.save()


def update_variants(variants, template, publish_progress=True):
	count = 0
	for d in variants:
		variant = frappe.get_doc("Item", d)
		copy_attributes_to_variant(template, variant)
		variant.save()

		count += 1
		if publish_progress:
			frappe.publish_progress(count*100/len(variants), title=_("Updating Variants..."))
