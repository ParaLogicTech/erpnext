# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
import erpnext
from frappe import _
from frappe.utils import cint, cstr, flt, sbool
from erpnext.setup.utils import get_exchange_rate
from frappe.model.document import Document
from erpnext.stock.get_item_details import (
	get_conversion_factor,
	get_price_list_data,
	get_default_warehouse,
	get_default_cost_center,
	get_item_packaging_details,
)
from erpnext.utilities.transaction_base import validate_uom_is_integer, validate_uom_is_convertible
from erpnext.stock.doctype.item_alternative.item_alternative import has_alternative_item
from frappe.core.doctype.version.version import get_diff
from frappe.model.utils import get_fetch_values
import functools


form_grid_templates = {
	"items": "templates/form_grid/item_grid.html"
}

force_fields = ["stock_uom", "is_packaging_material"]


class BOM(Document):
	def get_feed(self):
		return "For {0}".format(self.get('item_name') or self.get('item_code') or self.get('name'))

	def autoname(self):
		names = frappe.db.sql_list("""select name from `tabBOM` where item=%s""", self.item)

		if names:
			# name can be BOM/ITEM/001, BOM/ITEM/001-1, BOM-ITEM-001, BOM-ITEM-001-1

			# split by item
			names = [name.split(self.item, 1) for name in names]
			names = [d[-1][1:] for d in filter(lambda x: len(x) > 1 and x[-1], names)]

			# split by (-) if cancelled
			if names:
				names = [cint(name.split('-')[-1]) for name in names]
				idx = max(names) + 1
			else:
				idx = 1
		else:
			idx = 1

		self.name = 'BOM-' + self.item + ('-%.3i' % idx)

	def validate(self):
		self.validate_main_item()
		self.validate_currency()
		self.set_conversion_rate()
		self.set_plc_conversion_rate()
		validate_uom_is_convertible(self)
		validate_uom_is_integer(self, "uom", "qty", "BOM Item")
		self.set_carton_type_details()
		self.set_bom_material_details()
		self.validate_materials()
		self.validate_operations()
		self.update_cost(update_parent=False, from_child_bom=True, save=False)
		self.calculate_cost()

	def on_update(self):
		frappe.cache.hdel('bom_children', self.name)
		self.check_recursion()
		self.update_exploded_items()

	def before_submit(self):
		self.set_item_operation()

	def on_submit(self):
		self.manage_default_bom()

	def on_cancel(self):
		self.db_set("is_active", 0)
		self.db_set("is_default", 0)
		self.validate_bom_links()
		self.manage_default_bom()

	def on_update_after_submit(self):
		self.validate_bom_links()
		self.manage_default_bom()

	def onload(self):
		if self.docstatus == 0:
			if self.get('item'):
				self.update(get_fetch_values(self.doctype, 'item', self.item, skip_fetch_if_empty=True))

	def before_print(self, print_settings=None):
		self.company_address_doc = erpnext.get_company_address_doc(self)

		if self.docstatus == 0:
			if self.get('item'):
				self.update(get_fetch_values(self.doctype, 'item', self.item, skip_fetch_if_empty=True))

	@frappe.whitelist()
	def get_routing(self):
		if not self.get("routing"):
			return

		self.set("operations", [])
		routing_doc = frappe.get_cached_doc("Routing", self.routing)
		for r_op in routing_doc.operations:
			if r_op.condition:
				try:
					condition_met = frappe.safe_eval(r_op.condition, None, {
						"bom": self.as_dict(),
						"item": frappe.get_cached_doc("Item", self.item) if self.item else frappe._dict(),
					})
					if not condition_met:
						continue
				except Exception as e:
					frappe.throw(_("Error evaluating condition in Routing {0}: {1}").format(
						frappe.bold(self.routing), str(e)
					))

			bom_op = self.append('operations', {
				"operation": r_op.operation,
				"workstation": r_op.workstation,
				"description": r_op.description,
				"time_in_mins": flt(r_op.time_in_mins),
				"batch_size": cint(r_op.batch_size),
				"operating_cost": flt(r_op.operating_cost),
			})
			bom_op.hour_rate = flt(r_op.hour_rate / (flt(self.conversion_rate) or 1), 2)

	def validate_rm_item(self, item):
		if (item.name in [it.item_code for it in self.items]) and item.name == self.item:
			frappe.throw(_("Raw material cannot be same as main Item"))

	def set_carton_type_details(self):
		if self.packing_slip_required:
			packaging_details = get_item_packaging_details(self.item, self.carton_type)
			self.qty_per_carton = flt(packaging_details.get("qty_per_carton"))
		else:
			self.carton_type = None
			self.qty_per_carton = 0

	def set_bom_material_details(self):
		for item in self.get("items"):
			self.validate_bom_currency(item)
			self.set_bom_meterial_row_details(item)

	def set_bom_meterial_row_details(self, item):
		if item.do_not_explode:
			item.bom_no = None

		material_details = self.get_bom_material_detail({
			"item_code": item.item_code,
			"item_name": item.item_name,
			"bom_no": item.bom_no,
			"stock_qty": item.stock_qty,
			"qty": item.qty,
			"uom": item.uom,
			"stock_uom": item.stock_uom,
			"conversion_factor": item.conversion_factor,
			"skip_transfer_for_manufacture": item.skip_transfer_for_manufacture,
			"do_not_explode": item.do_not_explode,
		})

		for key in material_details:
			if not item.get(key) or key in force_fields:
				item.set(key, material_details[key])

	@frappe.whitelist()
	def get_bom_material_detail(self, args=None):
		""" Get raw material details like uom, desc and rate"""
		if not args:
			args = frappe.form_dict.get('args')

		if isinstance(args, str):
			import json
			args = json.loads(args)

		item = frappe.get_cached_doc("Item", args.get('item_code'))
		self.validate_rm_item(item)

		args['bom_no'] = args.get('bom_no') or item.default_bom or ''

		default_qty = 0 if args.get("scrap_items") else 1

		if args.get('skip_transfer_for_manufacture') is not None:
			args['skip_transfer_for_manufacture'] = cint(args.get('skip_transfer_for_manufacture'))
		else:
			args['skip_transfer_for_manufacture'] = cint(item.skip_transfer_for_manufacture)

		if not args.get('uom') and item.get('manufacture_uom'):
			args['uom'] = item.get('manufacture_uom')
			args['conversion_factor'] = get_conversion_factor(item.name, args['uom']).get("conversion_factor") or 1
			args['qty'] = flt(args.get('qty')) or default_qty
			args['stock_qty'] = args['qty'] * args['conversion_factor']

		rm_rate = self.get_rm_rate(args)
		child_unit_op_cost = self.get_bom_unit_operating_cost(args.get("bom_no"))

		ret_item = {
			'item_name': item.item_name,
			'description': item.description,
			'image': item.image,
			'stock_uom': item.stock_uom,
			'uom': args.get('uom') or item.get('stock_uom'),
			'conversion_factor': args.get('conversion_factor') or 1,
			'bom_no': args.get('bom_no') if not args.get('do_not_explode') else None,
			'rate': rm_rate,
			'qty': flt(args.get("qty")) or flt(args.get("stock_qty")) or default_qty,
			'stock_qty': flt(args.get("stock_qty")) or flt(args.get("qty")) or default_qty,
			'base_rate': flt(rm_rate) * (flt(self.conversion_rate) or 1),
			'skip_transfer_for_manufacture': args.get('skip_transfer_for_manufacture'),
			'has_alternative_item': has_alternative_item(item.name),
			'is_packaging_material': item.is_packaging_material,
			'child_unit_operating_cost': child_unit_op_cost,
			'base_child_unit_operating_cost': child_unit_op_cost * (flt(self.conversion_rate) or 1),
		}

		return ret_item

	@frappe.whitelist()
	def update_package_type_items(self, package_type):
		from erpnext.stock.doctype.packing_slip.packing_slip import get_package_type_details

		packaging_items = []
		if package_type:
			details = get_package_type_details(package_type, {
				"company": self.company,
				"doctype": self.doctype,
				"name": self.name,
			})
			packaging_items = details.get("packaging_items") or []

		to_remove = []
		package_type_row_names = set([d.package_type_row for d in packaging_items if d.package_type_row])
		for bom_item in self.items:
			if bom_item.for_packing_slip and bom_item.package_type_row not in package_type_row_names:
				to_remove.append(bom_item)

		for bom_item in to_remove:
			self.remove(bom_item)

		for pt_item in packaging_items:
			bom_item = [d for d in self.get("items") if d.for_packing_slip and d.package_type_row == pt_item.package_type_row]
			if bom_item:
				bom_item = bom_item[0]
			else:
				bom_item = self.append("items", frappe.new_doc("BOM Item"))

			pt_item.pop("source_warehouse", None)
			bom_item.update(pt_item)
			bom_item.for_packing_slip = 1
			bom_item.qty = (flt(self.carton_qty) * flt(pt_item.qty)) or 1
			self.set_bom_meterial_row_details(bom_item)

		self.calculate_cost()

	def validate_bom_currency(self, item):
		if item.get('bom_no') and frappe.db.get_value('BOM', item.get('bom_no'), 'currency') != self.currency:
			frappe.throw(_("Row {0}: Currency of the BOM #{1} should be equal to the selected currency {2}")
				.format(item.idx, item.bom_no, self.currency))

	def get_rm_rate(self, arg):
		"""Get raw material rate as per selected method, if bom exists takes bom cost"""
		rate = 0
		conversion_factor = flt(arg.get("conversion_factor") or 1)

		if not self.rm_cost_as_per:
			self.rm_cost_as_per = "Valuation Rate"

		if arg.get('scrap_items'):
			rate = self.get_valuation_rate(arg)
		elif arg:
			# Customer Provided parts will have zero rate
			if not frappe.get_cached_value('Item', arg["item_code"], 'is_customer_provided_item'):
				if arg.get("bom_no") and self.set_rate_of_sub_assembly_item_based_on_bom:
					base_bom_unit_cost = flt(frappe.db.get_value("BOM", arg['bom_no'], "base_unit_cost"))
					rate = base_bom_unit_cost * conversion_factor
				else:
					if self.rm_cost_as_per == 'Valuation Rate':
						rate = self.get_valuation_rate(arg) * conversion_factor

					elif self.rm_cost_as_per == 'Last Purchase Rate':
						last_purchase_rate = flt(
							arg.get('last_purchase_rate')
							or frappe.db.get_value("Item", arg['item_code'], "last_purchase_rate")
						)
						rate = last_purchase_rate * conversion_factor

					elif self.rm_cost_as_per == "Price List":
						if not self.buying_price_list:
							frappe.throw(_("Please select Price List"))
						args = frappe._dict({
							"doctype": "BOM",
							"price_list": self.buying_price_list,
							"qty": flt(arg.get("qty")) or 1,
							"uom": arg.get("uom") or arg.get("stock_uom"),
							"stock_uom": arg.get("stock_uom"),
							"transaction_type": "buying",
							"company": self.company,
							"currency": self.currency,
							"conversion_rate": 1,  # Passed conversion rate as 1 purposefully, as conversion rate is applied at the end of the function
							"conversion_factor": conversion_factor,
							"plc_conversion_rate": 1,
							"ignore_party": True
						})
						item_doc = frappe.get_cached_doc("Item", arg.get("item_code"))
						out = frappe._dict()
						get_price_list_data(args, item_doc, out)
						rate = out.price_list_rate

					if not rate:
						if self.rm_cost_as_per == "Price List":
							frappe.msgprint(_("Price not found for item {0} in price list {1}")
								.format(arg["item_code"], self.buying_price_list), alert=True)
						else:
							frappe.msgprint(_("{0} not found for item {1}")
								.format(self.rm_cost_as_per, arg["item_code"]), alert=True)

		return flt(rate) * flt(self.plc_conversion_rate or 1) / (self.conversion_rate or 1)

	@frappe.whitelist()
	def update_cost(self, update_parent=True, from_child_bom=False, save=True):
		if self.docstatus == 2:
			return
		if self.docstatus != 1:
			save = False

		existing_bom_cost = self.total_cost

		for d in self.get("items"):
			if not d.get("item_code"):
				continue

			d.is_packaging_material = frappe.get_cached_value("Item", d.item_code, "is_packaging_material")
			d.conversion_factor = get_conversion_factor(d.item_code, d.uom).get("conversion_factor") or 1
			d.stock_qty = flt(d.conversion_factor) * flt(d.qty)
			d.update(get_fetch_values(d.doctype, 'item_code', d.item_code))

			rate = self.get_rm_rate({
				"item_code": d.item_code,
				"bom_no": d.bom_no,
				"qty": d.qty,
				"uom": d.uom,
				"stock_uom": d.stock_uom,
				"conversion_factor": d.conversion_factor
			})
			if rate:
				d.rate = rate

			d.amount = flt(d.rate) * flt(d.qty)
			d.base_rate = flt(d.rate) * flt(self.conversion_rate)
			d.base_amount = flt(d.amount) * flt(self.conversion_rate)

			d.child_unit_operating_cost = self.get_bom_unit_operating_cost(d.get("bom_no"))
			d.base_child_unit_operating_cost = d.child_unit_operating_cost * flt(self.conversion_rate)

			if save:
				d.db_update()

		if self.docstatus == 1:
			self.flags.ignore_validate_update_after_submit = True

		self.calculate_cost()
		if save:
			self.db_update()
			self.notify_update()
		self.update_exploded_items()

		# update parent BOMs
		if self.total_cost != existing_bom_cost and update_parent:
			parent_boms = frappe.db.sql_list("""select distinct parent from `tabBOM Item`
				where bom_no = %s and docstatus=1 and parenttype='BOM'""", self.name)

			for bom in parent_boms:
				frappe.get_doc("BOM", bom).update_cost(from_child_bom=True)

		if not from_child_bom:
			frappe.msgprint(_("Cost Updated"), alert=True)

	def update_parent_cost(self):
		unit_cost = flt(self.base_unit_cost)
		unit_op_cost = flt(self.base_unit_operating_cost)

		frappe.db.sql("""
			update `tabBOM Item` i
			inner join `tabBOM` bom on bom.name = i.parent and i.parenttype = 'BOM'
			set
				i.base_rate = %(unit_cost)s,
				i.base_amount = i.stock_qty * %(unit_cost)s,
				i.rate = %(unit_cost)s / bom.conversion_rate,
				i.amount = (i.stock_qty * %(unit_cost)s) / bom.conversion_rate,
				i.base_child_unit_operating_cost = %(unit_op_cost)s,
				i.base_child_operating_cost = i.stock_qty * %(unit_op_cost)s,
				i.child_unit_operating_cost = %(unit_op_cost)s / bom.conversion_rate,
				i.child_operating_cost = (i.stock_qty * %(unit_op_cost)s) / bom.conversion_rate
			where i.bom_no = %(bom_no)s and bom.docstatus < 2
		""", {
			"unit_cost": unit_cost,
			"unit_op_cost": unit_op_cost,
			"bom_no": self.name,
		})

	def get_bom_unit_operating_cost(self, bom_no):
		if not bom_no:
			return 0

		base_child_unit_op_cost = flt(frappe.db.get_value("BOM", bom_no, "base_unit_operating_cost"))
		child_unit_op_cost = base_child_unit_op_cost / (self.conversion_rate or 1)

		return child_unit_op_cost

	def get_valuation_rate(self, args):
		""" Get weighted average of valuation rate from all warehouses """

		total_qty, total_value, valuation_rate = 0.0, 0.0, 0.0
		for d in frappe.db.sql("""select actual_qty, stock_value from `tabBin`
			where item_code=%s""", args['item_code'], as_dict=1):
				total_qty += flt(d.actual_qty)
				total_value += flt(d.stock_value)

		if total_qty:
			valuation_rate =  total_value / total_qty

		if valuation_rate <= 0:
			last_valuation_rate = frappe.db.sql("""select valuation_rate
				from `tabStock Ledger Entry`
				where item_code = %s and valuation_rate > 0
				order by posting_date desc, posting_time desc, creation desc limit 1""", args['item_code'])

			valuation_rate = flt(last_valuation_rate[0][0]) if last_valuation_rate else 0

		if not valuation_rate:
			valuation_rate = frappe.db.get_value("Item", args['item_code'], "valuation_rate")

		return flt(valuation_rate)

	def set_item_operation(self):
		if len(self.operations) < 1:
			return

		operation = self.operations[0].get('operation')
		for d in self.items:
			d.operation = operation

	def manage_default_bom(self):
		""" Uncheck others if current one is selected as default or
			check the current one as default if it the only bom for the selected item,
			update default bom in item master
		"""
		if self.is_default and self.is_active:
			from frappe.model.utils import set_default
			set_default(self, "item")
			item = frappe.get_doc("Item", self.item)
			if item.default_bom != self.name:
				frappe.db.set_value('Item', self.item, 'default_bom', self.name)
		elif not frappe.db.exists(dict(doctype='BOM', docstatus=1, item=self.item, is_default=1)) \
			and self.is_active:
			self.db_set("is_default", 1)
		else:
			self.db_set("is_default", 0)
			item = frappe.get_doc("Item", self.item)
			if item.default_bom == self.name:
				frappe.db.set_value('Item', self.item, 'default_bom', None)

	def validate_main_item(self):
		""" Validate main FG item"""
		item = frappe.get_cached_doc("Item", self.item)
		self.item_name = item.item_name
		self.description = item.description
		self.uom = item.stock_uom

		if not self.quantity:
			frappe.throw(_("Quantity should be greater than 0"))

	def validate_currency(self):
		if self.rm_cost_as_per == 'Price List':
			price_list_currency = frappe.db.get_value('Price List', self.buying_price_list, 'currency')
			if price_list_currency not in (self.currency, self.company_currency()):
				frappe.throw(_("Currency of the price list {0} must be {1} or {2}")
					.format(self.buying_price_list, self.currency, self.company_currency()))

	def set_conversion_rate(self):
		if self.currency == self.company_currency():
			self.conversion_rate = 1
		elif self.conversion_rate == 1 or flt(self.conversion_rate) <= 0:
			self.conversion_rate = get_exchange_rate(self.currency, self.company_currency(), args="for_buying")

	def set_plc_conversion_rate(self):
		if self.rm_cost_as_per in ["Valuation Rate", "Last Purchase Rate"]:
			self.plc_conversion_rate = 1
		elif not self.plc_conversion_rate and self.price_list_currency:
			self.plc_conversion_rate = get_exchange_rate(self.price_list_currency,
				self.company_currency(), args="for_buying")

	def validate_materials(self):
		""" Validate raw material entries """

		if not self.get('items'):
			frappe.throw(_("Raw Materials cannot be blank."))

		check_list = []
		for m in self.get('items'):
			if m.bom_no:
				validate_bom_no(m.item_code, m.bom_no)
			if flt(m.qty) <= 0:
				frappe.throw(_("Quantity required for Item {0} in row {1}").format(m.item_code, m.idx))
			check_list.append(m)

	def check_recursion(self, bom_list=[]):
		""" Check whether recursion occurs in any bom"""
		bom_list = self.traverse_tree()
		bom_nos = frappe.get_all('BOM Item', fields=["bom_no"],
			filters={'parent': ('in', bom_list), 'parenttype': 'BOM'})

		raise_exception = False
		if bom_nos and self.name in [d.bom_no for d in bom_nos]:
			raise_exception = True

		if not raise_exception:
			bom_nos = frappe.get_all('BOM Item', fields=["parent"],
				filters={'bom_no': self.name, 'parenttype': 'BOM'})

			if self.name in [d.parent for d in bom_nos]:
				raise_exception = True

		if raise_exception:
			frappe.throw(_("BOM recursion: {0} cannot be parent or child of {1}").format(self.name, self.name))

	def update_cost_and_exploded_items(self, bom_list=[]):
		bom_list = self.traverse_tree(bom_list)
		for bom in bom_list:
			bom_obj = frappe.get_doc("BOM", bom)
			bom_obj.check_recursion(bom_list=bom_list)
			bom_obj.update_exploded_items()

		return bom_list

	def traverse_tree(self, bom_list=None):
		def _get_children(bom_no):
			children = frappe.cache.hget('bom_children', bom_no)
			if children is None:
				children = frappe.db.sql_list("""
					SELECT bom_no FROM `tabBOM Item`
					WHERE parent = %s AND parenttype = 'BOM'
						AND bom_no != '' AND bom_no IS NOT NULL
					ORDER BY idx DESC
				""", bom_no)
				frappe.cache.hset('bom_children', bom_no, children)
			return children

		count = 0
		if not bom_list:
			bom_list = []

		if self.name not in bom_list:
			bom_list.append(self.name)

		while(count < len(bom_list)):
			for child_bom in _get_children(bom_list[count]):
				if child_bom not in bom_list:
					bom_list.append(child_bom)
			count += 1
		bom_list.reverse()
		return bom_list

	def calculate_cost(self):
		self.carton_qty = flt(self.quantity) / flt(self.qty_per_carton) if self.qty_per_carton else 0

		self.calculate_operating_cost()
		self.calculate_raw_material_cost()
		self.calculate_scrap_material_cost()

		self.total_cost = self.total_operating_cost + self.total_material_cost - self.scrap_material_cost
		self.base_total_cost = self.base_total_operating_cost + self.base_total_material_cost - self.base_scrap_material_cost

		self.unit_cost = self.total_cost / flt(self.quantity) if self.quantity else 0
		self.base_unit_cost = self.base_total_cost / flt(self.quantity) if self.quantity else 0

	def calculate_operating_cost(self):
		self.operating_cost = 0
		self.base_operating_cost = 0
		for d in self.get("operations"):
			if d.workstation and not d.hour_rate:
				hour_rate = flt(frappe.db.get_value("Workstation", d.workstation, "hour_rate"))
				d.hour_rate = hour_rate / flt(self.conversion_rate) if self.conversion_rate else hour_rate

			d.base_hour_rate = flt(d.hour_rate) * flt(self.conversion_rate)
			d.operating_cost = flt(d.hour_rate) * flt(d.time_in_mins) / 60.0
			d.base_operating_cost = d.operating_cost * flt(self.conversion_rate)

			self.operating_cost += d.operating_cost
			self.base_operating_cost += d.base_operating_cost

		self.additional_operating_cost = 0
		self.base_additional_operating_cost = 0
		for d in self.get("additional_costs"):
			d.base_rate = flt(d.rate) * flt(self.conversion_rate)
			d.amount = flt(d.rate) * flt(d.qty)
			d.base_amount = d.amount * flt(self.conversion_rate)

			self.additional_operating_cost += d.amount
			self.base_additional_operating_cost += d.base_amount

		self.child_operating_cost = 0
		self.base_child_operating_cost = 0
		for d in self.get("items"):
			d.stock_qty = flt(d.qty) * flt(d.conversion_factor)
			d.child_operating_cost = flt(d.child_unit_operating_cost) * flt(d.stock_qty)
			d.base_child_operating_cost = d.child_operating_cost * flt(self.conversion_rate)

			self.child_operating_cost += d.child_operating_cost
			self.base_child_operating_cost += d.base_child_operating_cost

		self.total_operating_cost = self.operating_cost + self.additional_operating_cost + self.child_operating_cost
		self.base_total_operating_cost = self.base_operating_cost + self.base_additional_operating_cost + self.base_child_operating_cost

		self.unit_operating_cost = self.total_operating_cost / flt(self.quantity) if self.quantity else 0
		self.base_unit_operating_cost = self.base_total_operating_cost / flt(self.quantity) if self.quantity else 0

	def calculate_raw_material_cost(self):
		self.total_material_cost = 0
		self.base_total_material_cost = 0
		self.raw_material_cost = 0
		self.base_raw_material_cost = 0
		self.packaging_material_cost = 0
		self.base_packaging_material_cost = 0
		self.total_raw_material_qty = 0

		for d in self.get("items"):
			d.base_rate = flt(d.rate) * flt(self.conversion_rate)
			d.amount = flt(d.rate) * flt(d.qty)
			d.base_amount = d.amount * flt(self.conversion_rate)

			d.stock_qty = flt(d.qty) * flt(d.conversion_factor)
			d.qty_consumed_per_unit = flt(d.stock_qty) / flt(self.quantity) if self.quantity else 0

			amount_without_op_cost = d.amount - flt(d.child_operating_cost)
			base_amount_without_op_cost = d.base_amount - flt(d.base_child_operating_cost)

			self.total_material_cost += amount_without_op_cost
			self.base_total_material_cost += base_amount_without_op_cost

			if d.is_packaging_material:
				self.packaging_material_cost += amount_without_op_cost
				self.base_packaging_material_cost += base_amount_without_op_cost
			else:
				self.raw_material_cost += amount_without_op_cost
				self.base_raw_material_cost += base_amount_without_op_cost

			self.total_raw_material_qty += flt(d.qty)

		self.unit_material_cost = self.total_material_cost / flt(self.quantity) if self.quantity else 0
		self.base_unit_material_cost = self.base_total_material_cost / flt(self.quantity) if self.quantity else 0

		self.unit_raw_material_cost = self.raw_material_cost / flt(self.quantity) if self.quantity else 0
		self.base_unit_raw_material_cost = self.base_raw_material_cost / flt(self.quantity) if self.quantity else 0

		self.unit_packaging_material_cost = self.packaging_material_cost / flt(self.quantity) if self.quantity else 0
		self.base_unit_packaging_material_cost = self.base_packaging_material_cost / flt(self.quantity) if self.quantity else 0

		self.total_raw_material_qty = flt(self.total_raw_material_qty, self.precision("total_raw_material_qty"))

	def calculate_scrap_material_cost(self):
		self.scrap_material_cost = 0
		self.base_scrap_material_cost = 0

		for d in self.get('scrap_items'):
			d.base_rate = flt(d.rate) * flt(self.conversion_rate)
			d.amount = flt(d.rate) * flt(d.stock_qty)
			d.base_amount = flt(d.amount) * flt(self.conversion_rate)

			self.scrap_material_cost += d.amount
			self.base_scrap_material_cost += d.base_amount

		self.unit_scrap_material_cost = self.scrap_material_cost / flt(self.quantity) if self.quantity else 0
		self.base_unit_scrap_material_cost = self.base_scrap_material_cost / flt(self.quantity) if self.quantity else 0

	def update_exploded_items(self):
		""" Update Flat BOM, following will be correct data"""
		self.get_exploded_items()
		self.add_exploded_items()

	def get_exploded_items(self):
		""" Get all raw materials including items from child bom"""
		self.cur_exploded_items = {}
		for d in self.get('items'):
			if not d.get("item_code"):
				continue
			if d.get("for_packing_slip"):
				continue

			if d.bom_no:
				self.get_child_exploded_items(d.bom_no, d.stock_qty, d.skip_transfer_for_manufacture)
			else:
				self.add_to_cur_exploded_items(frappe._dict({
					'item_code': d.item_code,
					'item_name': d.item_name,
					'operation': d.operation,
					'source_warehouse': d.source_warehouse,
					'description': d.description,
					'image': d.image,
					'uom': d.uom,
					'qty': flt(d.qty),
					'stock_uom': d.stock_uom,
					'stock_qty': flt(d.stock_qty),
					'rate': flt(d.base_rate),
					'skip_transfer_for_manufacture': d.skip_transfer_for_manufacture
				}))

	def company_currency(self):
		return erpnext.get_company_currency(self.company)

	def add_to_cur_exploded_items(self, args):
		key = (args.item_code, args.uom)
		if self.cur_exploded_items.get(key):
			self.cur_exploded_items[key]["qty"] += args.qty
			self.cur_exploded_items[key]["stock_qty"] += args.stock_qty
		else:
			self.cur_exploded_items[key] = args

	def get_child_exploded_items(self, bom_no, qty, skip_transfer_for_manufacture=0):
		""" Add all items from Flat BOM of child BOM"""
		# Did not use qty_consumed_per_unit in the query, as it leads to rounding loss
		child_fb_items = frappe.db.sql("""
			SELECT
				bom_item.item_code,
				bom_item.item_name,
				bom_item.description,
				bom_item.source_warehouse,
				bom_item.operation,
				bom_item.uom,
				bom_item.qty,
				bom_item.stock_uom,
				bom_item.stock_qty,
				bom_item.rate,
				bom_item.skip_transfer_for_manufacture,
				bom_item.qty / ifnull(bom.quantity, 1) AS qty_consumed_per_unit
			FROM `tabBOM Explosion Item` bom_item, tabBOM bom
			WHERE
				bom_item.parent = bom.name
				AND bom.name = %s
				AND bom.docstatus = 1
			order by bom_item.idx
		""", bom_no, as_dict=1)

		for d in child_fb_items:
			new_qty = d['qty_consumed_per_unit'] * qty
			new_stock_qty = new_qty * ((d['stock_qty'] / d['qty']) or 1)
			self.add_to_cur_exploded_items(frappe._dict({
				'item_code': d['item_code'],
				'item_name': d['item_name'],
				'source_warehouse': d['source_warehouse'],
				'operation': d['operation'],
				'description': d['description'],
				'uom': d['uom'],
				'qty': new_qty,
				'stock_uom': d['stock_uom'],
				'stock_qty': new_stock_qty,
				'rate': flt(d['rate']),
				'skip_transfer_for_manufacture': 1 if cint(skip_transfer_for_manufacture) else d.get('skip_transfer_for_manufacture', 0)
			}))

	def add_exploded_items(self):
		"""Add items to Flat BOM table"""

		old_exploded_items = self.get("exploded_items")
		old_exploded_items_map = {}
		for ch in old_exploded_items:
			key = (ch.item_code, ch.uom)
			old_exploded_items_map[key] = ch

		self.set("exploded_items", [])

		for i, key in enumerate(self.cur_exploded_items):
			if old_exploded_items_map.get(key):
				ch = self.append("exploded_items", old_exploded_items_map[key])
			else:
				ch = self.append("exploded_items", {})

			for f in self.cur_exploded_items[key].keys():
				ch.set(f, self.cur_exploded_items[key][f])

			ch.idx = i + 1
			ch.docstatus = self.docstatus

			ch.qty = flt(ch.qty, 6)
			ch.stock_qty = flt(ch.stock_qty, 6)

			ch.qty_consumed_per_unit = flt(flt(ch.qty) / flt(self.quantity), 9)
			ch.stock_qty_consumed_per_unit = flt(flt(ch.stock_qty) / flt(self.quantity), 9)

			ch.amount = flt(ch.qty) * flt(ch.rate)

		if self.docstatus == 1:
			self.update_child_table("exploded_items")

	def validate_bom_links(self):
		if not self.is_active:
			act_pbom = frappe.db.sql("""select distinct bom_item.parent from `tabBOM Item` bom_item
				where bom_item.bom_no = %s and bom_item.docstatus = 1 and bom_item.parenttype='BOM'
				and exists (select * from `tabBOM` where name = bom_item.parent
					and docstatus = 1 and is_active = 1)""", self.name)

			if act_pbom and act_pbom[0][0]:
				frappe.throw(_("Cannot deactivate or cancel BOM as it is linked with other BOMs"))

	def validate_operations(self):
		if self.with_operations:
			if not self.operations:
				frappe.throw(_("Operations cannot be left blank"))

			bom_operations = set()
			for d in self.operations:
				if not d.batch_size or d.batch_size <= 0:
					d.batch_size = 1

				bom_operations.add(d.operation)

			for d in self.items:
				if d.operation and d.operation not in bom_operations:
					frappe.throw(_("Row #{0}: Item Operation {1} not in BOM Operations")
						.format(d.idx, d.operation))

		else:
			self.set('operations', [])
			for d in self.items:
				d.operation = None


def get_bom_items_as_dict(
	bom,
	company,
	qty=1,
	fetch_exploded=1,
	fetch_scrap_items=0,
	include_non_stock_items=False,
	fetch_qty_in_stock_uom=True
):
	items_dict = {}

	# Did not use qty_consumed_per_unit in the query, as it leads to rounding loss
	query = """
		SELECT
			bom_item.item_code,
			item.item_name,
			sum(bom_item.{qty_field}/ifnull(bom.quantity, 1)) * %(qty)s as qty,
			bom_item.idx,
			item.image,
			bom.project,
			item.has_batch_no,
			item.stock_uom
			{select_columns}
		FROM `tab{table}` bom_item
		INNER JOIN `tabBOM` bom ON bom_item.parent = bom.name
		INNER JOIN `tabItem` item ON item.name = bom_item.item_code
		WHERE
			bom_item.docstatus < 2
			and bom.name = %(bom)s
			and item.is_stock_item in (1, {is_stock_item})
			{where_conditions}
		GROUP BY item_code, stock_uom
		ORDER BY idx
	"""

	is_stock_item = 0 if include_non_stock_items else 1
	if cint(fetch_exploded):
		uom_fields = ""
		if not fetch_qty_in_stock_uom:
			uom_fields = ", bom_item.stock_qty / bom_item.qty as conversion_factor, bom_item.uom"

		query = query.format(
			table="BOM Explosion Item",
			where_conditions="",
			is_stock_item=is_stock_item,
			qty_field="stock_qty" if fetch_qty_in_stock_uom else "qty",
			select_columns=""", bom_item.source_warehouse, bom_item.operation,
				bom_item.skip_transfer_for_manufacture, bom_item.description, bom_item.rate {0}
			""".format(uom_fields)
		)
		items = frappe.db.sql(query, { "parent": bom, "qty": qty, "bom": bom, "company": company }, as_dict=True)
	elif fetch_scrap_items:
		query = query.format(
			table="BOM Scrap Item",
			where_conditions="",
			select_columns=", bom_item.idx, item.description, bom_item.rate",
			is_stock_item=is_stock_item,
			qty_field="stock_qty"
		)
		items = frappe.db.sql(query, { "qty": qty, "bom": bom, "company": company }, as_dict=True)
	else:
		query = query.format(
			table="BOM Item",
			where_conditions=" and bom_item.for_packing_slip = 0",
			is_stock_item=is_stock_item,
			qty_field="stock_qty" if fetch_qty_in_stock_uom else "qty",
			select_columns = """, bom_item.uom, bom_item.conversion_factor, bom_item.source_warehouse,
				bom_item.idx, bom_item.operation, bom_item.skip_transfer_for_manufacture,
				bom_item.description, bom_item.base_rate as rate """
		)
		items = frappe.db.sql(query, { "qty": qty, "bom": bom, "company": company }, as_dict=True)

	# Create dict
	for item in items:
		if item.item_code in items_dict:
			items_dict[item.item_code]["qty"] += flt(item.qty)
		else:
			items_dict[item.item_code] = item

	# Set additional values
	for item, item_details in items_dict.items():
		item_doc = frappe.get_cached_doc("Item", item)
		defaults_args = frappe._dict({"company": company})

		item_details.default_warehouse = get_default_warehouse(item_doc, defaults_args)
		item_details.cost_center = get_default_cost_center(item_doc, defaults_args)

	return items_dict


@frappe.whitelist()
def get_bom_items(bom, company, qty=1, fetch_exploded=1):
	items = get_bom_items_as_dict(bom, company, qty, fetch_exploded, include_non_stock_items=True).values()
	items = list(items)
	items.sort(key = functools.cmp_to_key(lambda a, b: a.item_code > b.item_code and 1 or -1))
	return items


def validate_bom_no(item, bom_no):
	"""Validate BOM No of subcontracted items"""
	bom = frappe.get_doc("BOM", bom_no)

	if not bom.is_active:
		frappe.throw(_("BOM {0} must be active").format(bom_no))

	if bom.docstatus != 1:
		if not getattr(frappe.flags, "in_test", False):
			frappe.throw(_("BOM {0} must be submitted").format(bom_no))

	if item:
		rm_item_exists = False
		for d in bom.items:
			if d.item_code.lower() == item.lower():
				rm_item_exists = True

		for d in bom.scrap_items:
			if d.item_code.lower() == item.lower():
				rm_item_exists = True

		if bom.item.lower() == item.lower() or bom.item.lower() == cstr(frappe.get_cached_value("Item", item, "variant_of")).lower():
			rm_item_exists = True

		if not rm_item_exists:
			frappe.throw(_("BOM {0} does not belong to Item {1}").format(bom_no, item))


@frappe.whitelist()
def get_children(doctype, parent=None, is_root=False, **filters):
	is_root = sbool(is_root)

	if not parent or parent == "BOM":
		return []

	bom_doc = frappe.get_doc("BOM", parent)
	bom_doc.check_permission()

	if is_root:
		bom_items = [frappe._dict({
			"item_code": bom_doc.item, "value": bom_doc.name, "qty": bom_doc.quantity, "uom": bom_doc.uom
		})]
	else:
		bom_items = [
			frappe._dict({"item_code": d.item_code, "value": d.bom_no, "qty": d.qty, "uom": d.uom})
			for d in bom_doc.items
		]

	item_codes = list(set(d.get("item_code") for d in bom_items))
	items_map = {}
	if item_codes:
		items_data = frappe.get_all(
			"Item",
			fields=["name as item_code", "item_name", "item_group", "description", "stock_uom", "image"],
			filters={"name": ['in', item_codes]}
		)
		for d in items_data:
			items_map[d.item_code] = d

	for bom_item in bom_items:
		bom_item.update(items_map.get(bom_item.item_code, {}))
		bom_item.parent_bom_qty = bom_doc.quantity
		bom_item.expandable = 1 if bom_item.value else 0

	return bom_items


def get_boms_in_bottom_up_order(bom_no=None):
	from erpnext.manufacturing.doctype.bom.bom_tree import BOMGraph

	bom_nos = frappe.db.sql_list("""
		select name
		from `tabBOM`
		where docstatus = 1 and is_active = 1
	""")

	bom_edges = frappe.db.sql("""
		select bom.name as parent, i.bom_no as child
		from `tabBOM Item` i
		inner join `tabBOM` bom on bom.name = i.parent
		where ifnull(i.bom_no, '') != '' and bom.docstatus = 1 and bom.is_active = 1
	""", as_dict=1)

	bom_graph = BOMGraph(bom_nos)
	for d in bom_edges:
		bom_graph.add_edge(d.parent, d.child)

	sorted_boms = bom_graph.topological_sort(parent_bom=bom_no)

	return sorted_boms


def get_operating_cost_per_unit(
	bom_no=None,
	work_order_doc=None,
	default_expense_account=None,
	use_multi_level_bom=0
):
	unit_cost_map = {}
	if work_order_doc:
		for d in work_order_doc.get("operations"):
			expense_account = cstr(default_expense_account)
			unit_cost_map.setdefault(expense_account, 0)
			if flt(d.completed_qty):
				unit_cost_map[expense_account] += flt(d.actual_operating_cost) / flt(d.completed_qty)
			elif work_order_doc.qty:
				unit_cost_map[expense_account] += flt(d.planned_operating_cost) / flt(work_order_doc.qty)

		for d in work_order_doc.get("additional_costs"):
			expense_account = cstr(d.expense_account or default_expense_account)
			unit_cost_map.setdefault(expense_account, 0)
			unit_cost_map[expense_account] += flt(d.rate)

	elif bom_no:
		bom_doc = frappe.get_doc("BOM", bom_no)
		for d in bom_doc.get("operations"):
			expense_account = cstr(default_expense_account)
			unit_cost_map.setdefault(expense_account, 0)
			unit_cost_map[expense_account] += flt(d.base_operating_cost) / flt(bom_doc.quantity) if bom_doc.quantity else 0

		additional_costs = get_bom_additional_costs(bom_doc, use_multi_level_bom)
		for d in additional_costs:
			expense_account = cstr(d.expense_account or default_expense_account)
			unit_cost_map.setdefault(expense_account, 0)
			unit_cost_map[expense_account] += flt(d.rate)

	return unit_cost_map


def get_bom_additional_costs(bom_no, use_multi_level_bom=0):
	if isinstance(bom_no, Document):
		bom_doc = bom_no
		bom_no = bom_doc.name
	else:
		bom_doc = frappe.get_doc("BOM", bom_no)

	additional_costs = []

	def explode(parent_bom_doc, required_qty=1):
		if use_multi_level_bom:
			for item in parent_bom_doc.get("items"):
				if not item.bom_no:
					continue

				child_bom_doc = frappe.get_doc("BOM", item.bom_no)
				explode(child_bom_doc, item.stock_qty / parent_bom_doc.quantity)

		for cost in parent_bom_doc.get("additional_costs"):
			additional_costs.append(frappe._dict({
				"description": cost.description,
				"expense_account": cost.expense_account,
				"rate": flt(cost.base_amount) / flt(parent_bom_doc.quantity) * flt(required_qty)
			}))

	explode(bom_doc)

	return additional_costs


@frappe.whitelist()
def get_bom_diff(bom1, bom2):
	from frappe.model import table_fields

	if bom1 == bom2:
		frappe.throw(_("BOM 1 {0} and BOM 2 {1} should not be same")
			.format(frappe.bold(bom1), frappe.bold(bom2)))

	doc1 = frappe.get_doc('BOM', bom1)
	doc2 = frappe.get_doc('BOM', bom2)

	out = get_diff(doc1, doc2)
	out.row_changed = []
	out.added = []
	out.removed = []

	meta = doc1.meta

	identifiers = {
		'operations': 'operation',
		'items': 'item_code',
		'scrap_items': 'item_code',
		'exploded_items': 'item_code'
	}

	for df in meta.fields:
		old_value, new_value = doc1.get(df.fieldname), doc2.get(df.fieldname)

		if df.fieldtype in table_fields:
			identifier = identifiers[df.fieldname]
			# make maps
			old_row_by_identifier, new_row_by_identifier = {}, {}
			for d in old_value:
				old_row_by_identifier[d.get(identifier)] = d
			for d in new_value:
				new_row_by_identifier[d.get(identifier)] = d

			# check rows for additions, changes
			for i, d in enumerate(new_value):
				if d.get(identifier) in old_row_by_identifier:
					diff = get_diff(old_row_by_identifier[d.get(identifier)], d, for_child=True)
					if diff and diff.changed:
						out.row_changed.append((df.fieldname, i, d.get(identifier), diff.changed))
				else:
					out.added.append([df.fieldname, d.as_dict()])

			# check for deletions
			for d in old_value:
				if not d.get(identifier) in new_row_by_identifier:
					out.removed.append([df.fieldname, d.as_dict()])

	return out
