# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import flt, cint, cstr, combine_datetime, round_up
from frappe.model.mapper import map_child_doc, get_mapped_doc
from erpnext.controllers.transaction_controller import TransactionController
from erpnext.stock.get_item_details import (
	get_conversion_factor,
	get_hide_item_code,
	get_weight_per_unit,
	get_default_expense_account,
	get_default_cost_center,
	get_item_default_values,
	get_default_rejected_warehouse,
	get_force_default_warehouse,
	get_global_default_warehouse,
)
from erpnext.stock.utils import get_incoming_rate
from erpnext.accounts.party import validate_party_frozen_disabled
from erpnext.stock.doctype.batch.batch import auto_select_and_split_batches
from frappe.desk.reportview import get_filters_cond, get_match_cond
from erpnext.controllers.queries import get_fields
import json


class PackingSlip(TransactionController):
	item_table_fields = ["items", "packaging_items"]

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.force_item_fields = [
			"stock_uom", "has_batch_no", "has_serial_no", "force_default_warehouse", "item_group", "conversion_factor"
		]

		self.original_value_fields = [
			("original_customer", "customer"),
			("original_customer_name", "customer_name"),
		]

	def get_feed(self):
		return _("Packed {0}").format(self.get("package_type"))

	def before_validate_links(self):
		if self.docstatus == 0:
			self.set_original_values(unset=True)

	def onload(self):
		super().onload()
		if self.docstatus == 0:
			self.calculate_totals()

	def before_print(self, print_settings=None):
		# Hide 0 qty rows
		self.items = [d for d in self.items if d.qty]
		for i, d in enumerate(self.items):
			d.idx = i + 1

		super().before_print()

	def validate(self):
		self.validate_posting_time()
		super(PackingSlip, self).validate()
		self.validate_items()
		self.validate_purchase_order()
		self.validate_source_packing_slips()
		self.validate_sales_orders()
		self.validate_unpack_against()
		self.validate_with_previous_doc()
		self.validate_customer()
		self.validate_supplier()
		self.validate_warehouse()
		self.validate_uom_is_convertible(items_table_field="items")
		self.validate_uom_is_convertible(items_table_field="packaging_items")
		self.validate_uom_is_integer("uom", ["qty", "rejected_qty"])
		self.calculate_totals()
		self.validate_qty()
		self.validate_weights()
		self.set_cost_percentage()
		self.set_packed_items()
		self.set_title()
		self.set_unpacked_return_status()
		self.set_status(validate=False)

	def before_submit(self):
		self.set_original_values()
		self.validate_purchase_order_raw_material_qty()

	def on_submit(self):
		self.update_stock_ledger()
		self.make_gl_entries()
		self.update_previous_doc_status()

	def on_cancel(self):
		self.db_set({"status": "Cancelled", "warehouse": None})
		self.update_stock_ledger()
		self.make_gl_entries_on_cancel()
		self.update_previous_doc_status()

	def set_title(self):
		self.title = self.package_type
		if self.get("customer") or self.get("supplier"):
			self.title += " for {0}".format(self.customer_name or self.customer or self.supplier_name or self.supplier)

	def set_packed_items(self):
		packed_item_names = []
		for d in self.items:
			if d.item_name not in packed_item_names:
				packed_item_names.append(d.item_name)

		self.packed_items = ", ".join(packed_item_names)
		if len(self.packed_items) > 140:
			self.packed_items = self.packed_items[:137] + "..."

	def set_original_values(self, unset=False):
		for f in self.original_value_fields:
			if len(f) == 3:
				child_table_field, original_field, source_field = f
				for d in self.get(child_table_field):
					if unset:
						d.set(original_field, None)
					else:
						d.set(original_field, d.get(source_field))

			elif len(f) == 2:
				original_field, source_field = f
				if unset:
					self.set(original_field, None)
				else:
					self.set(original_field, self.get(source_field))

		if unset:
			self.is_reassigned = 0

	def set_missing_values(self, for_validate=False):
		self.set_package_type_details()
		self.set_missing_item_details(for_validate)
		self.set_source_packing_slips()

	def set_missing_item_details(self, for_validate=False):
		parent_args = self.as_dict()
		for field in self.item_table_fields:
			for item in self.get(field):
				if item.item_code:
					args = parent_args.copy()
					args.update(item.as_dict())
					args.doctype = self.doctype
					args.name = self.name
					args.child_doctype = item.doctype

					item_details = get_item_details(args)
					for f in item_details:
						if f in self.force_item_fields or item.get(f) in ("", None):
							item.set(f, item_details.get(f))

	def postprocess_after_mapping(self, reset_taxes=False):
		self.set_missing_values()
		self.calculate_totals()

	def set_package_type_details(self, force=False):
		if not self.get("package_type"):
			return

		package_type_details = get_package_type_details(self.package_type, self.as_dict())
		if package_type_details.weight_uom and (not self.weight_uom or force or self.is_new()):
			self.weight_uom = package_type_details.weight_uom

		if package_type_details.packaging_items and not self.is_unpack:
			if force:
				self.set("packaging_items", [])

			if not self.packaging_items:
				for d in package_type_details.packaging_items:
					row = frappe.new_doc("Packing Slip Packaging Material")
					row.update(d)
					self.append("packaging_items", row)

	def set_source_packing_slips(self):
		# Packing Slips from items table
		contents_packing_slips = []
		for d in self.get("items"):
			if d.get("source_packing_slip") and d.source_packing_slip not in contents_packing_slips:
				contents_packing_slips.append(d.source_packing_slip)

		# Remove
		packing_slips_visited = set()
		to_remove = []
		for d in self.get("packing_slips"):
			# remove if not in items
			if not d.source_packing_slip or d.source_packing_slip not in contents_packing_slips:
				to_remove.append(d)
				continue

			# remove if duplicate
			if d.source_packing_slip in packing_slips_visited:
				to_remove.append(d)

			packing_slips_visited.add(d.source_packing_slip)

		for d in to_remove:
			self.remove(d)

		# Add missing Packing Slips
		packages_packing_slips = [d.source_packing_slip for d in self.get("packing_slips") if d.get("source_packing_slip")]
		for source_packing_slips in contents_packing_slips:
			if source_packing_slips not in packages_packing_slips:
				new_row = self.append("packing_slips")
				new_row.source_packing_slip = source_packing_slips

		# Set details
		self.set_packing_slip_values()

	def set_packing_slip_values(self):
		for d in self.get("packing_slips"):
			details = frappe.db.get_value("Packing Slip", d.source_packing_slip,
				["package_type", "total_net_weight", "total_tare_weight", "total_gross_weight"], as_dict=1)

			if details:
				d.source_package_type = details.package_type
				d.net_weight = details.total_net_weight
				d.tare_weight = details.total_tare_weight
				d.gross_weight = details.total_gross_weight

	def validate_items(self):
		from erpnext.stock.doctype.item.item import validate_end_of_life, validate_is_not_template_item

		item_codes = []
		for field in self.item_table_fields:
			for d in self.get(field):
				if d.item_code:
					item_codes.append(d.item_code)

		stock_items = self.get_stock_items(item_codes)
		for field in self.item_table_fields:
			for d in self.get(field):
				if d.item_code:
					validate_end_of_life(d.item_code)
					validate_is_not_template_item(d.item_code)

					if d.item_code not in stock_items:
						frappe.throw(_("Row #{0}: {1} is not a stock Item")
							.format(d.idx, frappe.bold(d.item_code)))

	def validate_purchase_order(self):
		if self.get("purchase_order"):
			self.customer = None

			po = frappe.db.get_value("Purchase Order", self.purchase_order,
				['name', 'docstatus', 'status', 'company', 'supplier', 'is_subcontracted'], as_dict=1)

			if not po:
				frappe.throw(_("Purchase Order {0} does not exist").format(self.purchase_order))
			if po.docstatus != 1:
				frappe.throw(_("{0} is not submitted").format(frappe.get_desk_link("Purchase Order", po.name)))
			if po.status in ("Closed", "On Hold"):
				frappe.throw(_("{0} is {1}").format(
					frappe.get_desk_link("Purchase Order", po.name), po.status
				))

			if not po.is_subcontracted:
				frappe.throw(_("{0} is not a subcontracted order").format(
					frappe.get_desk_link("Purchase Order", po.name)
				))

			if self.company != po.company:
				frappe.throw(_("Company does not match with {0}. Company must be {1}").format(
					frappe.get_desk_link("Purchase Order", po.name), frappe.bold(po.company)
				))

			if self.supplier != po.supplier:
				frappe.throw(_("Supplier does not match with {0}. Supplier must be {1}").format(
					frappe.get_desk_link("Purchase Order", po.name), frappe.bold(po.supplier)
				))

			for d in self.items:
				if d.get("sales_order"):
					frappe.throw(_("Row #{0}: Packing Slip against a subcontracted Purchase Order cannot also include Sales Order").format(
						d.idx
					))
		else:
			self.supplier = None
			for d in self.items:
				d.purchase_order_item = None
				d.subcontracted_item = None
				d.subcontracted_item_name = None

	def validate_qty(self):
		all_zero = True

		for d in self.items:
			if self.is_unpack or d.get("source_packing_slip"):
				d.rejected_qty = 0
				d.stock_rejected_qty = 0

			if flt(d.qty):
				all_zero = False

			if not flt(d.qty) and not flt(d.rejected_qty):
				frappe.throw(_("Row #{0}: Item {1}, Quantity cannot be 0").format(d.idx, frappe.bold(d.item_code)))

			if self.is_unpack:
				if flt(d.qty) > 0:
					frappe.throw(_("Row #{0}: Item {1}, quantity must be negative number for unpacking")
					.format(d.idx, frappe.bold(d.item_code)))
			else:
				if flt(d.qty) < 0 or flt(d.rejected_qty) < 0:
					frappe.throw(_("Row #{0}: Item {1}, quantity must be positive number")
					.format(d.idx, frappe.bold(d.item_code)))

		if all_zero:
			frappe.throw(_("All items cannot have 0 quantity"))

	def validate_weights(self):
		weight_fields = ["net_weight", "tare_weight", "gross_weight"]

		for table_field in self.item_table_fields:
			for d in self.get(table_field):
				for weight_field in weight_fields:
					if self.is_unpack:
						if d.meta.has_field(weight_field) and flt(d.get(weight_field)) > 0:
							frappe.throw(_("Row #{0}: {1} must be negative for unpacking").format(
								d.idx, d.meta.get_label(weight_field)
							))
					else:
						if d.meta.has_field(weight_field) and flt(d.get(weight_field)) < 0:
							frappe.throw(_("Row #{0}: {1} cannot be negative").format(
								d.idx, d.meta.get_label(weight_field)
							))

		if self.is_unpack:
			if flt(self.total_tare_weight) > 0:
				frappe.throw(_("Total Tare Weight must be negative for unpacking"))
			if flt(self.total_gross_weight) > 0:
				frappe.throw(_("Total Gross Weight must be negative for unpacking"))
		else:
			if flt(self.total_tare_weight) < 0:
				frappe.throw(_("Total Tare Weight cannot be negative"))
			if flt(self.total_gross_weight) < 0:
				frappe.throw(_("Total Gross Weight cannot be negative"))

	def validate_warehouse(self):
		from erpnext.stock.utils import validate_warehouse_company

		warehouses = []
		for field in self.item_table_fields:
			warehouses += [d.source_warehouse for d in self.get(field) if d.get("source_warehouse")]

		warehouses = list(set(warehouses))
		for w in warehouses:
			validate_warehouse_company(w, self.company)

	def determine_warehouse_from_sales_order(self):
		sales_order_row_names = [d.sales_order_item for d in self.get("items") if d.get("sales_order_item")]
		if sales_order_row_names:
			warehouses = frappe.db.sql_list("""
				select distinct warehouse
				from `tabSales Order Item`
				where name in %s
			""", [sales_order_row_names])

			if warehouses and len(warehouses) == 1 and warehouses[0]:
				self.target_warehouse = warehouses[0]

	def validate_with_previous_doc(self):
		super(PackingSlip, self).validate_with_previous_doc({
			"Sales Order Item": {
				"ref_dn_field": "sales_order_item",
				"compare_fields": [["item_code", "="], ["uom", "="], ["conversion_factor", "="]],
				"is_child_table": True,
				"allow_duplicate_prev_row_id": True,
			},
			"Packing Slip Item": {
				"ref_dn_field": "packing_slip_item",
				"compare_fields": [
					["item_code", "="], ["uom", "="], ["conversion_factor", "="],
					["batch_no", "="], ["serial_no", "="],
				],
				"is_child_table": True,
			},
		})

		if self.get("is_unpack"):
			super(PackingSlip, self).validate_with_previous_doc({
				"Packing Slip Item": {
					"ref_dn_field": "unpack_against_row",
					"compare_fields": [
						["item_code", "="], ["uom", "="], ["conversion_factor", "="],
						["batch_no", "="], ["serial_no", "="],
					],
					"is_child_table": True,
				},
			})

			super(PackingSlip, self).validate_with_previous_doc({
				"Packing Slip Packaging Material": {
					"ref_dn_field": "unpack_against_row",
					"compare_fields": [
						["item_code", "="], ["batch_no", "="],
					],
					"is_child_table": True,
				},
			}, table_doctype="Packing Slip Packaging Material")

	def validate_source_packing_slips(self):
		def get_packing_slip_details(name):
			if not packing_slip_map.get(name):
				packing_slip_map[name] = frappe.db.get_value("Packing Slip", name, [
					"name", "docstatus", "status",
					"company", "customer", "supplier", "project", "weight_uom",
					"posting_date", "posting_time"
				], as_dict=1)

			return packing_slip_map[name]

		packing_slip_map = {}

		# Validate Packing Slips
		for d in self.get("items"):
			if d.get("source_packing_slip"):
				if d.source_packing_slip == self.name:
					frappe.throw(_("Row #{0}: Source Packing Slip cannot be the same as the Target Packing Slip"))

				packing_slip = get_packing_slip_details(d.source_packing_slip)
				if not packing_slip:
					frappe.throw(_("Row #{0}: Packing Slip {1} does not exist").format(d.source_packing_slip))

				if packing_slip.docstatus == 0:
					frappe.throw(_("Row #{0}: Source {1} is in draft").format(
						d.idx, frappe.get_desk_link("Packing Slip", packing_slip.name)
					))
				if packing_slip.docstatus == 2:
					frappe.throw(_("Row #{0}: Source {1} is cancelled").format(
						d.idx, frappe.get_desk_link("Packing Slip", packing_slip.name)
					))

				if (packing_slip.status != "In Stock" and not self.is_unpack) or (packing_slip.status != "Nested" and self.is_unpack):
					frappe.throw(_("Row #{0}: Cannot select Source {1} because its status is {2}").format(
						d.idx, frappe.get_desk_link("Packing Slip", packing_slip.name), frappe.bold(packing_slip.status)
					))

				if self.company != packing_slip.company:
					frappe.throw(_("Row #{0}: Company does not match with Source {1}. Company must be {2}").format(
						d.idx, frappe.get_desk_link("Packing Slip", packing_slip.name), frappe.bold(packing_slip.company)
					))

				if cstr(self.project) != cstr(packing_slip.project):
					frappe.throw(_("Row #{0}: Project does not match with Source {1}. Project must be {2}").format(
						d.idx, frappe.get_desk_link("Packing Slip", packing_slip.name), frappe.bold(packing_slip.project)
					))

				if packing_slip.customer and self.customer != packing_slip.customer:
					frappe.throw(_("Row #{0}: Customer does not match with Source {1}. Customer must be {2}").format(
						d.idx, frappe.get_desk_link("Packing Slip", packing_slip.name), frappe.bold(packing_slip.customer)
					))

				if packing_slip.supplier and self.supplier != packing_slip.supplier:
					frappe.throw(_("Row #{0}: Supplier does not match with Source {1}. Supplier must be {2}").format(
						d.idx, frappe.get_desk_link("Packing Slip", packing_slip.name), frappe.bold(packing_slip.supplier)
					))

				if self.weight_uom != packing_slip.weight_uom:
					frappe.throw(_("Row #{0}: Weight UOM does not match with Source {1}. Weight UOM must be {2}").format(
						d.idx, frappe.get_desk_link("Packing Slip", packing_slip.name), frappe.bold(packing_slip.weight_uom)
					))

				source_packing_dt = combine_datetime(packing_slip.posting_date, packing_slip.posting_time)
				nested_packing_dt = combine_datetime(self.posting_date, self.posting_time)
				if nested_packing_dt < source_packing_dt:
					frappe.throw(_("Row #{0}: Nested Packing Date/Time cannot be before Source {1} Date/Time {2}").format(
						d.idx,
						frappe.get_desk_link("Packing Slip", packing_slip.name),
						frappe.bold(frappe.format(source_packing_dt))
					))

				# Validate Packing Slip Item
				if not d.packing_slip_item:
					frappe.throw(_("Row #{0}: Missing Source Packing Slip Row Reference").format(d.idx))

				packing_slip_item = frappe.db.get_value("Packing Slip Item", d.packing_slip_item,
					['qty', 'net_weight', 'tare_weight', 'gross_weight'], as_dict=1)

				if not packing_slip_item:
					frappe.throw(_("Row #{0}: Invalid Source Packing Slip Row Reference").format(d.idx))

				if self.is_unpack:
					packing_slip_item.qty *= -1
					packing_slip_item.net_weight *= -1
					packing_slip_item.tare_weight *= -1
					packing_slip_item.gross_weight *= -1

				if flt(d.qty) != packing_slip_item.qty:
					frappe.throw(_("Row #{0}: Qty does not match with Source {1}. Qty must be {2}").format(
						d.idx,
						frappe.get_desk_link("Packing Slip", packing_slip.name),
						frappe.bold(frappe.format(packing_slip_item.qty))
					))

				if flt(d.net_weight, d.precision("net_weight")) != flt(packing_slip_item.net_weight, d.precision("net_weight")):
					frappe.throw(_("Row #{0}: Net Weight does not match with Source {1}. Net Weight must be {2}").format(
						d.idx,
						frappe.get_desk_link("Packing Slip", packing_slip.name),
						frappe.bold(frappe.format(packing_slip_item.net_weight))
					))
				if flt(d.tare_weight, d.precision("tare_weight")) != flt(packing_slip_item.tare_weight, d.precision("tare_weight")):
					frappe.throw(_("Row #{0}: Tare Weight does not match with Source {1}. Tare Weight must be {2}").format(
						d.idx,
						frappe.get_desk_link("Packing Slip", packing_slip.name),
						frappe.bold(frappe.format(packing_slip_item.tare_weight))
					))
				if flt(d.gross_weight, d.precision("gross_weight")) != flt(packing_slip_item.gross_weight, d.precision("gross_weight")):
					frappe.throw(_("Row #{0}: Gross Weight does not match with Source {1}. Gross Weight must be {2}").format(
						d.idx,
						frappe.get_desk_link("Packing Slip", packing_slip.name),
						frappe.bold(frappe.format(packing_slip_item.gross_weight))
					))

	def validate_sales_orders(self):
		sales_orders = list(set([d.sales_order for d in self.get("items") if d.get("sales_order")]))
		sales_order_map = {}
		for sales_order in sales_orders:
			details = frappe.db.get_value("Sales Order", sales_order,
				["name", "docstatus", "status", "company", "customer", "customer_name", "project"], as_dict=1)
			sales_order_map[sales_order] = details

		customer_details = frappe._dict({})
		for d in self.get("items"):
			if not d.get("sales_order"):
				continue

			order_details = sales_order_map[d.sales_order]
			if order_details.docstatus == 0:
				frappe.throw(_("Row #{0}: {1} is Draft. Please submit it first.").format(
					d.idx, frappe.get_desk_link("Sales Order", order_details.name)))
			if order_details.docstatus == 2:
				frappe.throw(_("Row #{0}: {1} is cancelled").format(
					d.idx, frappe.get_desk_link("Sales Order", order_details.name)))
			if order_details.status in ("Closed", "On Hold"):
				frappe.throw(_("Row #{0}: {1} status is {2}").format(
					d.idx, frappe.get_desk_link("Sales Order", order_details.name), frappe.bold(order_details.status)))

			if self.company != order_details.company:
				frappe.throw(_("Row #{0}: {1} Company {2} does not match with Packing Slip").format(
					d.idx, frappe.get_desk_link("Sales Order", order_details.name), frappe.bold(order_details.company)
				))

			if cstr(self.project) != cstr(order_details.project):
				frappe.throw(_("Row #{0}: {1} Project {2} does not match with Packing Slip").format(
					d.idx, frappe.get_desk_link("Sales Order", order_details.name), frappe.bold(order_details.project)
				))

			if customer_details and customer_details.customer != order_details.customer:
				frappe.throw(_("Row #{0}: {1} Customer {2} does not match with Row #{3} {4} Customer {5}").format(
					d.idx,
					frappe.get_desk_link("Sales Order", order_details.name),
					order_details.customer_name or order_details.customer,
					customer_details.row.idx,
					frappe.get_desk_link("Sales Order", customer_details.sales_order),
					customer_details.customer_name or customer_details.customer,
				))

			customer_details.customer = order_details.customer
			customer_details.customer_name = order_details.customer_name
			customer_details.row = d
			customer_details.sales_order = d.sales_order

		if customer_details and customer_details.customer:
			self.customer = customer_details.customer
			self.customer_name = customer_details.customer_name

	def validate_unpack_against(self):
		if not self.get("is_unpack"):
			return

		if not self.get("unpack_against"):
			frappe.throw(_("Missing Unpack Against Packing Slip"))

		unpack_against = frappe.db.get_value("Packing Slip", self.unpack_against, [
			"name", "docstatus", "status",
			"company", "customer", "supplier", "package_type", "warehouse",
			"posting_date", "posting_time"
		], as_dict=1)

		if not unpack_against:
			frappe.throw(_("Unpack Against Packing Slip {0} does not exist").format(frappe.bold(self.unpack_against)))

		if unpack_against.docstatus != 1:
			frappe.throw(_("Unpack Against {0} is not submitted").format(
				frappe.get_desk_link("Packing Slip", unpack_against.name)
			))

		if unpack_against.status not in ("In Stock", "Rejected"):
			frappe.throw(_("Cannot Unpack Against {0} because its status is {1}").format(
				frappe.get_desk_link("Packing Slip", unpack_against.name), frappe.bold(unpack_against.status)
			))

		if self.company != unpack_against.company:
			frappe.throw(_("Company does not match with Unpack Against {0}. Company must be {1}").format(
				frappe.get_desk_link("Packing Slip", unpack_against.name), frappe.bold(unpack_against.company)
			))

		if unpack_against.customer and self.customer != unpack_against.customer:
			frappe.throw(_("Customer does not match with Unpack Against {0}. Customer must be {1}").format(
				frappe.get_desk_link("Packing Slip", unpack_against.name), frappe.bold(unpack_against.customer)
			))

		if unpack_against.supplier and self.supplier != unpack_against.supplier:
			frappe.throw(_("Supplier does not match with Unpack Against {0}. Supplier must be {1}").format(
				frappe.get_desk_link("Packing Slip", unpack_against.name), frappe.bold(unpack_against.supplier)
			))

		if self.package_type != unpack_against.package_type:
			frappe.throw(_("Package Type does not match with Unpack Against {0}. Package Type must be {1}").format(
				frappe.get_desk_link("Packing Slip", unpack_against.name), frappe.bold(unpack_against.package_type)
			))

		if self.target_warehouse != unpack_against.warehouse:
			frappe.throw(_("Target Warehouse does not match with Unpack Against {0}. Target Warehouse must be {1}").format(
				frappe.get_desk_link("Packing Slip", unpack_against.name), frappe.bold(unpack_against.warehouse)
			))

		unpack_against_dt = combine_datetime(unpack_against.posting_date, unpack_against.posting_time)
		self_dt = combine_datetime(self.posting_date, self.posting_time)
		if self_dt < unpack_against_dt:
			frappe.throw(_("Unpacking Date/Time cannot be before Packing Date/Time {0}").format(frappe.format(self_dt)))

		for d in self.get("items"):
			if not d.get("unpack_against_row"):
				frappe.throw(_("Row #{0}: Missing Unpack Against Row Reference").format(d.idx))

			unpacked_against_row = frappe.db.get_value("Packing Slip Item", d.unpack_against_row,
				['qty', 'net_weight', 'tare_weight', 'gross_weight'], as_dict=1)

			if not unpacked_against_row:
				frappe.throw(_("Row #{0}: Invalid Unpack Against Row Reference").format(d.idx))

			unpacked_against_row.qty *= -1
			unpacked_against_row.net_weight *= -1
			unpacked_against_row.tare_weight *= -1
			unpacked_against_row.gross_weight *= -1

			if flt(d.qty) != unpacked_against_row.qty:
				frappe.throw(_("Row #{0}: Qty does not match with Unpack Against {1}. Qty must be {2}").format(
					d.idx,
					frappe.get_desk_link("Packing Slip", unpack_against.name),
					frappe.bold(frappe.format(unpacked_against_row.qty))
				))

			# if flt(d.net_weight, d.precision("net_weight")) != flt(unpacked_against_row.net_weight, d.precision("net_weight")):
			# 	frappe.throw(_("Row #{0}: Net Weight does not match with Unpack Against {1}. Net Weight must be {2}").format(
			# 		d.idx,
			# 		frappe.get_desk_link("Packing Slip", unpack_against.name),
			# 		frappe.bold(frappe.format(unpacked_against_row.net_weight))
			# 	))
			# if flt(d.tare_weight, d.precision("tare_weight")) != flt(unpacked_against_row.tare_weight, d.precision("tare_weight")):
			# 	frappe.throw(_("Row #{0}: Tare Weight does not match with Unpack Against {1}. Tare Weight must be {2}").format(
			# 		d.idx,
			# 		frappe.get_desk_link("Packing Slip", unpack_against.name),
			# 		frappe.bold(frappe.format(unpacked_against_row.tare_weight))
			# 	))
			# if flt(d.gross_weight, d.precision("gross_weight")) != flt(unpacked_against_row.gross_weight, d.precision("gross_weight")):
			# 	frappe.throw(_("Row #{0}: Gross Weight does not match with Unpack Against {1}. Gross Weight must be {2}").format(
			# 		d.idx,
			# 		frappe.get_desk_link("Packing Slip", unpack_against.name),
			# 		frappe.bold(frappe.format(unpacked_against_row.gross_weight))
			# 	))

	def validate_work_orders(self):
		for d in self.get("items"):
			if d.get("work_order"):
				work_order_details = frappe.db.get_value("Work Order", d.work_order, [
					"name", "docstatus",
					"production_item", "project", "customer",
					"sales_order", "sales_order_item", "company"
				], as_dict=1)

				if not work_order_details:
					frappe.throw(_("Row #{0}: Work Order {1} does not exist").format(d.idx, d.work_order))

				if work_order_details.docstatus != 1:
					frappe.throw(_("Row #{0}: Work Order {1} is not submitted").format(
						d.idx, frappe.get_desk_link("Work Order", work_order_details.name))
					)

				if d.item_code != work_order_details.production_item:
					frappe.throw(_("Row #{0}: Item Code does not match with Work Order {1}. Item Code must be {2}").format(
						d.idx,
						frappe.get_desk_link("Work Order", work_order_details.name),
						frappe.bold(work_order_details.production_item)
					))

				if cstr(d.sales_order) != cstr(work_order_details.sales_order):
					frappe.throw(_("Row #{0}: Sales Order does not match with Work Order {1}. Sales Order must be {2}").format(
						d.idx,
						frappe.get_desk_link("Work Order", work_order_details.name),
						frappe.bold(work_order_details.sales_order)
					))

				if cstr(d.sales_order_item) != cstr(work_order_details.sales_order_item):
					frappe.throw(_("Row #{0}: Sales Order row reference does not match with Work Order {1}").format(
						d.idx,
						frappe.get_desk_link("Work Order", work_order_details.name),
					))

				if self.company != work_order_details.company:
					frappe.throw(_("Row #{0}: Company does not match with Work Order {1}. Company must be {2}").format(
						d.idx,
						frappe.get_desk_link("Work Order", work_order_details.name),
						frappe.bold(work_order_details.company)
					))

				if cstr(self.project) != cstr(work_order_details.project):
					frappe.throw(_("Row #{0}: {1} Project {2} does not match with Packing Slip").format(
						d.idx,
						frappe.get_desk_link("Work Order", work_order_details.name),
						frappe.bold(work_order_details.project)
					))

				if self.customer and work_order_details.customer and self.customer != work_order_details.customer:
					frappe.throw(_("Row #{0}: {1} Customer {2} does not match with Packing Slip").format(
						d.idx,
						frappe.get_desk_link("Work Order", work_order_details.name),
						frappe.bold(work_order_details.customer)
					))

	def validate_customer(self):
		if self.get("customer"):
			validate_party_frozen_disabled("Customer", self.customer)
			self.customer_name = frappe.get_cached_value("Customer", self.customer, "customer_name")
		else:
			self.customer_name = None

	def validate_supplier(self):
		if self.get("supplier"):
			validate_party_frozen_disabled("Supplier", self.supplier)
			self.supplier_name = frappe.get_cached_value("Supplier", self.supplier, "supplier_name")
		else:
			self.supplier_name = None

	def calculate_totals(self):
		self.total_qty = 0
		self.total_stock_qty = 0
		self.total_rejected_qty = 0
		self.total_stock_rejected_qty = 0
		self.total_net_weight = 0
		self.total_tare_weight = 0

		for field in self.item_table_fields:
			for item in self.get(field):
				self.round_floats_in(item,
					excluding=['net_weight_per_unit', 'tare_weight_per_unit', 'gross_weight_per_unit'])

				if self.is_unpack or item.get("source_packing_slip"):
					item.rejected_qty = 0

				item.stock_qty = flt(item.qty * item.conversion_factor, 6)
				if item.meta.has_field("rejected_qty"):
					item.stock_rejected_qty = flt(item.rejected_qty * item.conversion_factor, 6)

				if item.meta.has_field("net_weight_per_unit"):
					item.net_weight = flt(item.net_weight_per_unit * item.stock_qty, item.precision("net_weight"))
				if item.meta.has_field("tare_weight_per_unit"):
					item.tare_weight = flt(item.tare_weight_per_unit * item.stock_qty, item.precision("tare_weight"))
				if item.meta.has_field("gross_weight"):
					item.gross_weight = flt(item.net_weight + item.tare_weight, item.precision("gross_weight"))
					if item.stock_qty and item.meta.has_field("gross_weight_per_unit"):
						item.gross_weight_per_unit = item.gross_weight / item.stock_qty

				if field == "items":
					self.total_qty += item.qty
					self.total_stock_qty += item.stock_qty

				if item.meta.has_field("rejected_qty"):
					self.total_rejected_qty += item.rejected_qty
					self.total_stock_rejected_qty += item.stock_rejected_qty

				if not item.get("source_packing_slip"):
					self.total_net_weight += flt(item.get("net_weight"))
					self.total_tare_weight += flt(item.get("tare_weight"))

		for d in self.get("packing_slips"):
			if self.is_unpack:
				self.total_net_weight -= d.net_weight
				self.total_tare_weight -= d.tare_weight
			else:
				self.total_net_weight += d.net_weight
				self.total_tare_weight += d.tare_weight

		self.round_floats_in(self, [
			'total_qty', 'total_stock_qty', 'total_rejected_qty', 'total_stock_rejected_qty', 'total_net_weight', 'total_tare_weight',
		])
		self.total_gross_weight = flt(self.total_net_weight + self.total_tare_weight, self.precision("total_gross_weight"))

	def set_target_warehouse_as_source_warehouse(self):
		source_warehouses = set([d.source_warehouse for d in self.get("items")])
		if len(source_warehouses) == 1:
			self.target_warehouse = list(source_warehouses)[0]

	@frappe.whitelist()
	def auto_select_batches(self):
		auto_select_and_split_batches(self, 'source_warehouse', additional_group_fields=[
			"sales_order", "sales_order_item",
			"subcontracted_item", "purchase_order_item",
		])
		self.run_method("calculate_totals")

	def set_cost_percentage(self):
		total_cost = 0
		total_stock_qty = 0

		for d in self.get("items"):
			args = self.get_args_for_incoming_rate(d)
			d.valuation_rate = get_incoming_rate(args, raise_error_if_no_rate=False)
			d.valuation_amount = flt(d.valuation_rate) * flt(d.stock_qty)

			total_cost += d.valuation_amount
			total_stock_qty += flt(d.stock_qty)

		for d in self.get("items"):
			if total_cost:
				d.cost_percentage = d.valuation_amount / total_cost * 100
			else:
				d.cost_percentage = flt(d.stock_qty) / total_stock_qty * 100 if total_stock_qty else 0

	def get_args_for_incoming_rate(self, item):
		return frappe._dict({
			"item_code": item.item_code,
			"warehouse": item.source_warehouse,
			"batch_no": item.batch_no,
			"posting_date": self.posting_date,
			"posting_time": self.posting_time,
			"qty": -1 * flt(item.stock_qty),
			"serial_no": item.get("serial_no"),
			"voucher_type": self.doctype,
			"voucher_no": self.name,
			"company": self.company,
			"allow_zero_valuation": cint(item.get("allow_zero_valuation_rate")),
		})

	def update_previous_doc_status(self):
		sales_orders = set()
		so_row_names_without_wos = set()
		work_orders = set()
		packing_slips = set()

		for d in self.items:
			# Get non nested orders from items
			if not d.get("source_packing_slip"):
				if d.sales_order:
					sales_orders.add(d.sales_order)
				if d.sales_order_item and not d.work_order:
					so_row_names_without_wos.add(d.sales_order_item)
				if d.work_order:
					work_orders.add(d.work_order)

			# Get nested from
			if d.get("source_packing_slip"):
				packing_slips.add(d.source_packing_slip)

		self.update_work_order_packing_status(work_orders)

		for name in sales_orders:
			doc = frappe.get_doc("Sales Order", name)
			doc.set_production_packing_status(update=True)
			doc.validate_packed_qty(from_doctype=self.doctype, row_names=so_row_names_without_wos)
			doc.notify_update()

		if self.is_unpack and self.unpack_against:
			packing_slips.add(self.unpack_against)

		for name in packing_slips:
			doc = frappe.get_doc("Packing Slip", name)
			doc.set_status(update=True)
			doc.notify_update()

		if self.purchase_order:
			doc = frappe.get_doc("Purchase Order", self.purchase_order)
			doc.set_raw_materials_packed_qty(update=True)
			doc.notify_update()

	def update_work_order_packing_status(self, work_orders):
		for name in work_orders:
			doc = frappe.get_doc("Work Order", name)
			doc.set_packing_status(update=True)
			doc.validate_overpacking(from_doctype=self.doctype)
			doc.notify_update()

	def update_stock_ledger(self, allow_negative_stock=False):
		sl_entries = []

		# Packaging Material
		self.get_packaging_material_sles(sl_entries)

		# Package Contents Transfer between Packing Slip
		if not self.is_unpack:
			self.get_packing_transfer_sles(sl_entries)
		else:
			self.get_unpack_transfer_sles(sl_entries)

		# Reverse for cancellation
		if self.docstatus == 2:
			sl_entries.reverse()
		
		self.make_sl_entries(sl_entries, self.amended_from and 'Yes' or 'No', allow_negative_stock=allow_negative_stock)

	def get_packaging_material_sles(self, sl_entries):
		for d in self.get("packaging_items"):
			# OUT SLE for packaging material (or IN for Unpack)
			sle_material = self.get_sl_entries(d, {
				"warehouse": d.source_warehouse,
				"actual_qty": -flt(d.stock_qty),
			})

			# Unpack IN at same rate
			if self.is_unpack and d.unpack_against_row and self.docstatus == 1:
				sle_material.dependencies = [{
					"dependent_voucher_type": self.doctype,
					"dependent_voucher_no": self.unpack_against,
					"dependent_voucher_detail_no": d.unpack_against_row,
					"dependency_type": "Amount",
				}]

			sl_entries.append(sle_material)

	def get_packing_transfer_sles(self, sl_entries):
		for d in self.get("items"):
			# OUT SLE for items contents from source warehouse
			outgoing_qty = flt(d.stock_qty) + flt(d.stock_rejected_qty)
			sle_out = self.get_sl_entries(d, {
				"warehouse": d.source_warehouse,
				"actual_qty": -outgoing_qty,
				"packing_slip": d.get("source_packing_slip"),
				"is_transfer": 1,
			})

			# Disabled nesting dependency because cost may get updated during handling
			# if d.get("source_packing_slip") and d.get("packing_slip_item") and self.docstatus == 1:
			# 	# Nesting Dependency
			# 	sle_out.dependencies = [{
			# 		"dependent_voucher_type": self.doctype,
			# 		"dependent_voucher_no": d.source_packing_slip,
			# 		"dependent_voucher_detail_no": d.packing_slip_item,
			# 		"dependency_type": "Rate",
			# 		"dependency_qty_filter": "Negative",
			# 	}]

			sl_entries.append(sle_out)

			# IN SLE for item contents to target warehouse
			if flt(d.stock_qty):
				sle_in = self.get_sl_entries(d, {
					"warehouse": self.target_warehouse,
					"actual_qty": flt(d.stock_qty),
					"packing_slip": self.name,
					"is_transfer": 1,
				})

				if self.docstatus == 1:
					# Transfer Dependency
					sle_in.dependencies = [{
						"dependent_voucher_type": self.doctype,
						"dependent_voucher_no": self.name,
						"dependent_voucher_detail_no": d.name,
						"dependency_type": "Rate",
						"dependency_qty_filter": "Negative"
					}]

					# Include Consumed Packaging Material in Valuation
					for dep_row in self.get("packaging_items"):
						if flt(dep_row.stock_qty) and d.cost_percentage:
							sle_in.dependencies.append({
								"dependent_voucher_type": self.doctype,
								"dependent_voucher_no": self.name,
								"dependent_voucher_detail_no": dep_row.name,
								"dependency_type": "Amount",
								"dependency_percentage": d.cost_percentage
							})

				sl_entries.append(sle_in)

			# IN SLE for rejected qty
			if d.rejected_qty:
				if not d.rejected_warehouse:
					frappe.throw(_("Row #{0}: Rejected Warehouse is required for packing rejection").format(d.idx))

				rejected_sle_in = self.get_sl_entries(d, {
					"warehouse": d.rejected_warehouse,
					"actual_qty": flt(d.stock_rejected_qty),
					"is_transfer": 1,
				})

				if self.docstatus == 1:
					rejected_sle_in.dependencies = [{
						"dependent_voucher_type": self.doctype,
						"dependent_voucher_no": self.name,
						"dependent_voucher_detail_no": d.name,
						"dependency_type": "Rate",
						"dependency_qty_filter": "Negative",
					}]

				sl_entries.append(rejected_sle_in)

	def get_unpack_transfer_sles(self, sl_entries):
		for d in self.get("items"):
			# Unpack OUT SLE for items contents from target warehouse
			sle_out = self.get_sl_entries(d, {
				"warehouse": self.target_warehouse,
				"actual_qty": flt(d.stock_qty),
				"packing_slip": self.unpack_against,
				"is_transfer": 1,
			})

			# Unpack OUT at same rate, disabled because cost may get updated
			# if self.docstatus == 1 and d.unpack_against_row:
			# 	sle_out.dependencies = [{
			# 		"dependent_voucher_type": self.doctype,
			# 		"dependent_voucher_no": self.unpack_against,
			# 		"dependent_voucher_detail_no": d.unpack_against_row,
			# 		"dependency_type": "Rate",
			# 		"dependency_qty_filter": "Negative",
			# 	}]

			sl_entries.append(sle_out)

			# Unpack IN SLE for item contents to source warehouse
			sle_in = self.get_sl_entries(d, {
				"warehouse": d.source_warehouse,
				"actual_qty": -flt(d.stock_qty),
				"packing_slip": d.get("source_packing_slip"),
				"is_transfer": 1,
			})

			if self.docstatus == 1:
				# Transfer Dependency
				sle_in.dependencies = [{
					"dependent_voucher_type": self.doctype,
					"dependent_voucher_no": self.name,
					"dependent_voucher_detail_no": d.name,
					"dependency_type": "Amount",
				}]

				# Include Packaging Material in Cost
				for dep_row in self.get("packaging_items"):
					if flt(dep_row.stock_qty) and d.cost_percentage:
						sle_in.dependencies.append({
							"dependent_voucher_type": self.doctype,
							"dependent_voucher_no": self.name,
							"dependent_voucher_detail_no": dep_row.name,
							"dependency_type": "Amount",
							"dependency_percentage": d.cost_percentage
						})

			sl_entries.append(sle_in)

	def get_stock_voucher_items(self, sle_map):
		return self.get("items") + self.get("packaging_items")

	def set_status(self, update=False, status=None, update_modified=True, validate=True):
		previous_status = self.status

		self.warehouse, is_delivered, is_nested, is_unpacked = self.process_packing_slip_ledger(validate=validate)
		is_rejected = 0
		if self.warehouse:
			is_rejected = cint(frappe.get_cached_value("Warehouse", self.warehouse, "stock_type") == "Rejected")

		if self.docstatus == 0:
			self.status = "Draft"
		elif self.docstatus == 1:
			if is_unpacked or cint(self.is_unpack):
				self.status = "Unpacked"
			elif is_nested:
				self.status = "Nested"
			elif is_delivered:
				self.status = "Delivered"
			elif is_rejected:
				self.status = "Rejected"
			else:
				self.status = "In Stock"
		else:
			self.status = "Cancelled"

		if self.status == "In Stock":
			has_sales_order = any(d.sales_order for d in self.items)
			has_source_packing_slip = any(d.source_packing_slip for d in self.items)
			if (has_sales_order and not self.is_reassigned) or has_source_packing_slip:
				self.can_reassign = 0
			else:
				self.can_reassign = 1
		else:
			self.can_reassign = 0

		self.add_status_comment(previous_status)

		if update:
			self.db_set({
				"status": self.status,
				"warehouse": self.warehouse,
				"can_reassign": self.can_reassign,
			}, update_modified=update_modified)

	def process_packing_slip_ledger(self, validate=False):
		def get_qty_map(packing_slip_item_key, sles, is_incoming=False):
			qty_map = frappe._dict({"warehouses": set(), "items": {}})
			for sle in sles:
				if is_incoming and sle.is_transfer and sle.actual_qty < 0:
					continue

				qty_map["warehouses"].add(sle.warehouse)

				against_row = sle.get(packing_slip_item_key)
				qty_map["items"].setdefault(against_row, 0)
				qty_map["items"][against_row] += sle.actual_qty

			to_remove = []
			for against_row in qty_map["items"]:
				qty_map["items"][against_row] = flt(qty_map["items"][against_row], 9)

				if not is_incoming:
					qty_map["items"][against_row] *= -1

				if not qty_map["items"][against_row]:
					to_remove.append(against_row)

			for against_row in to_remove:
				del qty_map["items"][against_row]

			qty_map["warehouses"] = list(qty_map["warehouses"])
			return qty_map

		warehouse = None
		is_nested = 0
		is_unpacked = 0
		is_delivered = 0

		packed_qty_map = {}
		if self.docstatus == 1:
			if not self.is_unpack:
				warehouse = self.target_warehouse

			for d in self.get("items"):
				packed_qty_map[d.name] = flt(d.stock_qty)

		voucher_wise_sle_map = self.get_voucher_wise_stock_ledger_entries()

		for (voucher_type, voucher_no), sl_entries in voucher_wise_sle_map.items():
			if voucher_type == "Packing Slip":
				# Packing
				if voucher_no == self.name:
					qty_map = get_qty_map("voucher_detail_no", sl_entries, is_incoming=True)
					packed_qty_map = qty_map["items"]
					warehouse = qty_map["warehouses"][0]

				# Unnesting
				elif sl_entries[0].is_unnest:
					qty_map = get_qty_map("nest_against_row", sl_entries, is_incoming=True)
					if qty_map["items"] == packed_qty_map:
						is_nested = 0
						warehouse = qty_map["warehouses"][0]
					elif validate and qty_map["items"]:
						self.raise_incomplete_fulfilment("unpacked", "unpacking", voucher_type, voucher_no)

				# Unpacking
				elif sl_entries[0].is_unpack:
					qty_map = get_qty_map("unpack_against_row", sl_entries, is_incoming=False)
					if qty_map["items"] == packed_qty_map:
						is_unpacked = 1
						warehouse = None
					elif validate and qty_map["items"]:
						self.raise_incomplete_fulfilment("unpacked", "unpacking", voucher_type, voucher_no)

				# Nesting
				elif sl_entries[0].source_packing_slip:
					qty_map = get_qty_map("nest_against_row", sl_entries, is_incoming=False)
					if qty_map["items"] == packed_qty_map:
						is_nested = 1
						warehouse = None
					elif validate and qty_map["items"]:
						self.raise_incomplete_fulfilment("nested", "nesting", voucher_type, voucher_no)

				# Invalid Entry
				else:
					frappe.throw(_("Invalid Entry"))

			elif voucher_type in ("Delivery Note", "Sales Invoice"):
				key = "invoice_against_row" if voucher_type == "Sales Invoice" else "deliver_against_row"
				# Delivery Return
				if sl_entries[0].dn_is_return or sl_entries[0].si_is_return:
					qty_map = get_qty_map(key, sl_entries, is_incoming=True)
					if qty_map["items"] == packed_qty_map:
						is_delivered = 0
						warehouse = qty_map["warehouses"][0]
					elif validate and qty_map["items"]:
						self.raise_incomplete_fulfilment("returned", "return", voucher_type, voucher_no)

					if len(qty_map["warehouses"]) != 1:
						self.raise_multiple_target_warehouse(voucher_type, voucher_no)

				# Delivery
				else:
					qty_map = get_qty_map(key, sl_entries, is_incoming=False)
					if qty_map["items"] == packed_qty_map:
						is_delivered = 1
						warehouse = None
					elif validate and qty_map["items"]:
						self.raise_incomplete_fulfilment("delivered", "delivery", voucher_type, voucher_no)

			elif voucher_type == "Stock Entry":
				# Material Transfer
				if sl_entries[0].purpose == "Material Transfer":
					qty_map = get_qty_map("ste_against_row", sl_entries, is_incoming=True)
					if qty_map["items"] == packed_qty_map:
						warehouse = qty_map["warehouses"][0]
					elif validate and qty_map["items"]:
						self.raise_incomplete_fulfilment("transferred", "transfer", voucher_type, voucher_no)

					if len(qty_map["warehouses"]) != 1:
						self.raise_multiple_target_warehouse(voucher_type, voucher_no)

				# Material Issue
				if sl_entries[0].purpose == "Material Issue":
					qty_map = get_qty_map("ste_against_row", sl_entries, is_incoming=False)
					if qty_map["items"] == packed_qty_map:
						is_unpacked = 1
						warehouse = None
					elif validate and qty_map["items"]:
						self.raise_incomplete_fulfilment("unpacked", "unpack", voucher_type, voucher_no)

				# Send to Subcontractor
				if sl_entries[0].purpose == "Send to Subcontractor":
					qty_map = get_qty_map("ste_against_row", sl_entries, is_incoming=False)
					if qty_map["items"] == packed_qty_map:
						is_delivered = 1
						warehouse = None
					elif validate and qty_map["items"]:
						self.raise_incomplete_fulfilment("delivered", "delivery", voucher_type, voucher_no)

		return warehouse, is_delivered, is_nested, is_unpacked

	def get_voucher_wise_stock_ledger_entries(self):
		sl_entries = []
		if self.docstatus == 1:
			sl_entries = frappe.db.sql("""
				select
					sle.voucher_type, sle.voucher_no, sle.voucher_detail_no,
					sle.item_code, sle.warehouse, sle.actual_qty, sle.is_transfer,
					ps.is_unpack, psi.unpack_against_row,
					psi.source_packing_slip, psi.packing_slip_item as nest_against_row,
					dn.is_return as dn_is_return, dni.packing_slip_item as deliver_against_row,
					si.is_return as si_is_return, sii.packing_slip_item as invoice_against_row,
					ste.purpose, sti.packing_slip_item as ste_against_row
				from `tabStock Ledger Entry` sle
				left join `tabPacking Slip` ps on sle.voucher_type = 'Packing Slip' and sle.voucher_no = ps.name
				left join `tabPacking Slip Item` psi on psi.parent = ps.name and psi.name = sle.voucher_detail_no
				left join `tabDelivery Note` dn on sle.voucher_type = 'Delivery Note' and sle.voucher_no = dn.name
				left join `tabDelivery Note Item` dni on dni.parent = dn.name and dni.name = sle.voucher_detail_no
				left join `tabSales Invoice` si on sle.voucher_type = 'Sales Invoice' and sle.voucher_no = si.name
				left join `tabSales Invoice Item` sii on sii.parent = si.name and sii.name = sle.voucher_detail_no
				left join `tabStock Entry` ste on sle.voucher_type = 'Stock Entry' and sle.voucher_no = ste.name
				left join `tabStock Entry Detail` sti on sti.parent = ste.name and sti.name = sle.voucher_detail_no
				where sle.packing_slip = %s
				order by sle.posting_date, sle.posting_time, sle.creation
			""", self.name, as_dict=True)

		sle_map = {}
		for sle in sl_entries:
			if sle.is_unpack and sle.actual_qty > 0:
				sle.is_unnest = 1

			voucher_key = (sle.voucher_type, sle.voucher_no)
			sle_map.setdefault(voucher_key, []).append(sle)

		return sle_map

	def raise_incomplete_fulfilment(self, past, present, voucher_type, voucher_no):
		frappe.throw(_(
			"Some items from {0} are not completely {1} by {2}. "
			"Partial {3} of Package is not allowed. "
			"Please select all items of Packing Slip."
		).format(
			frappe.get_desk_link("Packing Slip", self.name),
			_(past),
			frappe.get_desk_link(voucher_type, voucher_no),
			_(present),
		))

	def raise_multiple_target_warehouse(self, voucher_type, voucher_no):
		frappe.throw(_(
			"{0} has multiple target warehouses against {1}. "
			"Please select only one target warehouse for the Packing Slip."
		).format(
			frappe.get_desk_link(voucher_type, voucher_no),
			frappe.get_desk_link("Packing Slip", self.name),
		))

	def set_unpacked_return_status(self, update=False, update_modified=True,
			update_work_orders=True, update_source_packing_slip=True, row_names=None):
		if not row_names:
			row_names = [d.name for d in self.items]

		unpacked_return_qty_map = self.get_unpacked_return_qty_map()
		for d in self.items:
			d.unpacked_return_qty = flt(unpacked_return_qty_map.get(d.name))
			if update:
				d.db_set("unpacked_return_qty", d.unpacked_return_qty, update_modified=update_modified)

		if update:
			if update_work_orders:
				work_orders = set([d.work_order for d in self.items if d.work_order and d.name in row_names])
				self.update_work_order_packing_status(work_orders)

			if update_source_packing_slip:
				source_packing_slips = set([d.source_packing_slip for d in self.items if d.source_packing_slip and d.name in row_names])
				source_row_names = [d.packing_slip_item for d in self.items if d.source_packing_slip and d.name in row_names]
				for packing_slip in source_packing_slips:
					packing_slip_doc = frappe.get_doc("Packing Slip", packing_slip)
					packing_slip_doc.set_unpacked_return_status(update=update, update_modified=update_modified,
						update_work_orders=update_work_orders, update_source_packing_slip=update_source_packing_slip,
						row_names=source_row_names)

	def get_unpacked_return_qty_map(self):
		unpacked_return_qty_map = {}
		if self.docstatus != 1:
			return unpacked_return_qty_map

		row_names = [d.name for d in self.items]
		if not row_names:
			return unpacked_return_qty_map

		unpacked_returns_by_delivery_note = frappe.db.sql("""
			select against_i.packing_slip_item, -1 * return_i.qty as qty
			from `tabDelivery Note Item` return_i
			inner join `tabDelivery Note Item` against_i on against_i.name = return_i.delivery_note_item
			inner join `tabDelivery Note` return_p on return_p.name = return_i.parent
			where return_p.docstatus = 1 and return_p.is_return = 1 and return_p.reopen_order = 1
				and against_i.packing_slip_item in %s
				and ifnull(return_i.packing_slip, '') = ''
				and ifnull(against_i.packing_slip, '') != ''
		""", [row_names], as_dict=1)

		unpacked_returns_by_sales_invoice = frappe.db.sql("""
			select against_i.packing_slip_item, -1 * return_i.qty as qty
			from `tabSales Invoice Item` return_i
			inner join `tabSales Invoice Item` against_i on against_i.name = return_i.sales_invoice_item
			inner join `tabSales Invoice` return_p on return_p.name = return_i.parent
			where return_p.docstatus = 1 and return_p.update_stock = 1 and return_p.is_return = 1 and return_p.reopen_order = 1
				and against_i.packing_slip_item in %s
				and ifnull(return_i.packing_slip, '') = ''
				and ifnull(against_i.packing_slip, '') != ''
		""", [row_names], as_dict=1)

		unpacked_returns_by_packing_slip = frappe.db.sql("""
			select nested_i.packing_slip_item, nested_i.unpacked_return_qty as qty
			from `tabPacking Slip Item` nested_i
			where nested_i.docstatus = 1 and nested_i.packing_slip_item in %s
		""", [row_names], as_dict=1)

		for d in unpacked_returns_by_delivery_note + unpacked_returns_by_sales_invoice + unpacked_returns_by_packing_slip:
			unpacked_return_qty_map.setdefault(d.packing_slip_item, 0)
			unpacked_return_qty_map[d.packing_slip_item] += d.qty

		return unpacked_return_qty_map

	def reassign_sales_order(self, sales_order=None, ignore_permissions=True):
		# Validate Packing Slip can be reassigned
		if self.docstatus != 1:
			frappe.throw(_("{0} is not submitted").format(
				frappe.get_desk_link("Packing Slip", self.name)
			))

		if self.status != "In Stock":
			frappe.throw(_("{0} cannot be reassigned because it's status is {1} and not 'In Stock'").format(
				frappe.get_desk_link("Packing Slip", self.name),
				self.status,
			))

		# no change
		has_sales_orders = set(d.sales_order for d in self.items if d.sales_order)
		if sales_order and sales_order in has_sales_orders:
			frappe.throw(_("{0} is already assigned to {1}").format(
				frappe.get_desk_link("Packing Slip", self.name),
				frappe.get_desk_link("Sales Order", sales_order),
			))

		if not sales_order and not has_sales_orders:
			frappe.throw(_("{0} is not assigned to any Sales Order").format(
				frappe.get_desk_link("Packing Slip", self.name)
			))

		if has_sales_orders and not self.is_reassigned:
			frappe.throw(_("Cannot reassign {0} because it was packed for another Sales Order").format(
				frappe.get_desk_link("Packing Slip", self.name)
			))

		has_source_packing_slip = any(d.source_packing_slip for d in self.items)
		if has_source_packing_slip:
			frappe.throw(_("Cannot reassign nested {0}").format(
				frappe.get_desk_link("Packing Slip", self.name)
			))

		if not self.can_reassign:
			frappe.throw(_("Reassignment of {0} is not allowed").format(
				frappe.get_desk_link("Packing Slip", self.name)
			))

		# Check if Sales Order can be assigned
		grouped_items = self.group_items_by(("item_code", "uom"))
		target_so_doc = None
		if sales_order:
			target_so_doc = frappe.get_doc("Sales Order", sales_order)

			if not ignore_permissions:
				target_so_doc.check_permission("read")

			if target_so_doc.docstatus != 1:
				frappe.throw(_("{0} is not submitted").format(
					frappe.get_desk_link("Sales Order", target_so_doc.name)
				))

			if target_so_doc.status in ("Closed", "On Hold"):
				frappe.throw(_("{0} is {1}").format(
					frappe.get_desk_link("Sales Order", target_so_doc.name),
					frappe.bold(target_so_doc.status),
				))

			if target_so_doc.delivery_status != "To Deliver":
				frappe.throw(_("{0} is not deliverable").format(
					frappe.get_desk_link("Sales Order", target_so_doc.name)
				))

			# Check if Items match
			for (ps_item_code, ps_uom), ps_group in grouped_items.items():
				valid_so_item = None
				low_qty_so_item = None
				for so_item in target_so_doc.items:
					if ps_item_code != so_item.item_code:
						continue
					if ps_uom != so_item.uom:
						continue

					so_item.packing_assignable_qty = get_packing_assignable_qty(
						so_item.qty, so_item.delivered_qty, so_item.packed_qty, so_item.work_order_qty
					)
					if so_item.packing_assignable_qty <= 0:
						continue

					if flt(ps_group.total_qty) <= so_item.packing_assignable_qty:
						valid_so_item = so_item
						break
					else:
						low_qty_so_item = so_item

				matched_so_item = valid_so_item
				if not matched_so_item:
					qty_suggestion_message = ""
					if low_qty_so_item:
						qty_suggestion_message = _("Found Row #{0}, however, maximum Qty that can be assigned is {1} {2}").format(
							low_qty_so_item.idx,
							frappe.bold(frappe.format(
								low_qty_so_item.packing_assignable_qty,
								df=low_qty_so_item.meta.get_field("qty")
							)),
							low_qty_so_item.uom,
						)

					frappe.throw(_("{0} does not have any pending Item {1} to be packed that can be assigned with {2}. {3}").format(
						frappe.get_desk_link("Sales Order", target_so_doc.name),
						frappe.bold(ps_item_code),
						frappe.get_desk_link("Packing Slip", self.name),
						qty_suggestion_message,
					))

				ps_group.matched_so_item = matched_so_item

		self.update_reassign_sales_order(grouped_items, target_so_doc)
		self.notify_update()

		# Version log
		if target_so_doc:
			self.add_comment("Label", _("Reassigned to {0}").format(
				frappe.get_desk_link("Sales Order", target_so_doc.name)
			))
		else:
			self.add_comment("Label", _("Unassigned Sales Order"))

	def update_reassign_sales_order(self, grouped_items, target_so_doc=None):
		# Reassign
		sales_orders_to_update = set([d.sales_order for d in self.items if d.sales_order])
		if target_so_doc:
			sales_orders_to_update.add(target_so_doc.name)

		# Set Updated Customer
		if target_so_doc:
			self.customer = target_so_doc.customer
			self.customer_name = target_so_doc.customer_name
			self.is_reassigned = 1
		else:
			self.customer = self.original_customer
			self.customer_name = self.original_customer_name
			self.is_reassigned = 0

		self.db_set({
			"customer": self.customer,
			"customer_name": self.customer_name,
			"is_reassigned": self.is_reassigned,
		})

		# Set SO Reference
		for ps_group in grouped_items.values():
			for ps_item in ps_group['items']:
				ps_item.sales_order = target_so_doc.name if target_so_doc else None
				ps_item.sales_order_item = ps_group.matched_so_item.name if target_so_doc else None
				ps_item.db_set({
					"sales_order": ps_item.sales_order,
					"sales_order_item": ps_item.sales_order_item,
				})

		# Update SO Status
		for so_name in sales_orders_to_update:
			if target_so_doc and so_name == target_so_doc.name:
				so = target_so_doc
			else:
				so = frappe.get_doc("Sales Order", so_name)

			so.set_production_packing_status(update=True)
			so.validate_packed_qty(from_doctype=self.doctype)
			so.notify_update()


@frappe.whitelist()
def get_package_type_details(package_type, args):
	if isinstance(args, str):
		args = json.loads(args)

	packaging_items_copy_fields = [
		"item_code", "item_name", "description",
		"qty", "uom", "conversion_factor", "stock_qty",
		"tare_weight_per_unit", "source_warehouse",
	]

	package_type_doc = frappe.get_cached_doc("Package Type", package_type)
	if package_type_doc.weight_uom:
		args["weight_uom"] = package_type_doc.weight_uom

	args["child_doctype"] = "Packing Slip Packaging Material"

	packaging_items = []
	for d in package_type_doc.get("packaging_items"):
		if d.get("item_code"):
			item_row = {k: d.get(k) for k in packaging_items_copy_fields}

			item_args = args.copy()
			item_args.update(item_row)

			item_details = get_item_details(item_args)
			item_row.update(item_details)

			packaging_items.append(item_row)

	return frappe._dict({
		"packaging_items": packaging_items,
		"weight_uom": package_type_doc.weight_uom,
	})


@frappe.whitelist()
def get_item_details(args):
	if isinstance(args, str):
		args = json.loads(args)

	args = frappe._dict(args)
	out = frappe._dict()

	if not args.item_code:
		frappe.throw(_("Item Code is mandatory"))

	item = frappe.get_cached_doc("Item", args.item_code)

	# Basic Item Details
	out.item_name = item.item_name
	out.description = item.description
	out.hide_item_code = get_hide_item_code(item, args)
	out.has_batch_no = item.has_batch_no
	out.has_serial_no = item.has_serial_no
	out.item_group = item.item_group

	# Qty and UOM
	out.qty = flt(args.qty) or 1
	out.stock_uom = item.stock_uom
	if not args.get('uom'):
		args.uom = item.stock_uom

	if args.uom == item.stock_uom:
		out.uom = args.uom
		out.conversion_factor = 1
	else:
		conversion = get_conversion_factor(item.name, args.uom)
		if conversion.get('not_convertible'):
			out.uom = item.stock_uom
			out.conversion_factor = 1
		else:
			out.uom = args.uom
			out.conversion_factor = flt(conversion.get("conversion_factor"))

	out.stock_qty = flt(out.qty * out.conversion_factor, 6)

	# Weight Per Unit
	out.net_weight_per_unit = flt(args.net_weight_per_unit) or get_weight_per_unit(item.name,
		weight_uom=args.weight_uom or item.weight_uom)
	out.tare_weight_per_unit = flt(args.tare_weight_per_unit) or get_weight_per_unit(item.name,
		weight_uom=args.weight_uom or item.weight_uom, weight_field="tare_weight_per_unit")

	# Warehouse
	out.source_warehouse = get_default_source_warehouse(item, args)
	out.rejected_warehouse = get_default_rejected_warehouse(item, args)
	out.force_default_warehouse = get_force_default_warehouse(item, args)

	# Subcontracting
	if args.subcontracted_item:
		out.subcontracted_item_name = frappe.get_cached_value("Item", args.get("subcontracted_item"), "item_name")
	elif args.purchase_order:
		from erpnext.buying.doctype.purchase_order.purchase_order import get_subcontracted_item_from_material_item
		out.update(get_subcontracted_item_from_material_item(args.item_code, args.purchase_order))

	# Accounting
	if args.company:
		stock_adjustment_account = frappe.get_cached_value('Company', args.company, 'stock_adjustment_account')
		out.expense_account = stock_adjustment_account or get_default_expense_account(args.item_code, args)
		out.cost_center = get_default_cost_center(args.item_code, args)

	frappe.utils.call_hook_method("packing_slip_get_item_details", args, out)

	return out


def get_default_source_warehouse(item, args):
	warehouse = args.get("source_warehouse")
	if not warehouse:
		parent_warehouse = args.get("default_source_warehouse")

		default_values = get_item_default_values(item, args)
		default_warehouse = default_values.get("default_warehouse")

		force_default_warehouse = get_force_default_warehouse(item, args)
		if force_default_warehouse:
			warehouse = default_warehouse
		else:
			warehouse = parent_warehouse or default_warehouse

		if not warehouse:
			warehouse = get_global_default_warehouse(args.get("company"))

	return warehouse


@frappe.whitelist()
def get_item_weights_per_unit(item_codes, weight_uom=None):
	if isinstance(item_codes, str):
		item_codes = json.loads(item_codes)

	if not item_codes:
		return {}

	out = {}
	for item_code in item_codes:
		item_weight_uom = frappe.get_cached_value("Item", item_code, "weight_uom")
		out[item_code] = {
			"net_weight_per_unit": get_weight_per_unit(item_code, weight_uom=weight_uom or item_weight_uom),
			"tare_weight_per_unit": get_weight_per_unit(item_code, weight_uom=weight_uom or item_weight_uom,
				weight_field="tare_weight_per_unit"),
		}

	return out


@frappe.whitelist()
def make_target_packing_slip(source_name, target_doc=None):
	if isinstance(source_name, str):
		packing_slip_names = [source_name]
	else:
		packing_slip_names = source_name

	target_warehouses = set()

	for ps_name in packing_slip_names:
		source_packing_slip = frappe.get_doc("Packing Slip", ps_name)
		if source_packing_slip.get("target_warehouse"):
			target_warehouses.add(source_packing_slip.target_warehouse)

		target_doc = map_target_document("Packing Slip", target_doc, source_packing_slip)

		packing_slip_item_mapper = {
			"doctype": "Packing Slip Item",
			"field_map": {
				"parent": "source_packing_slip",
				"name": "packing_slip_item",
				"sales_order": "sales_order",
				"sales_order_item": "sales_order_item",
				"purchase_order_item": "purchase_order_item",
				"subcontracted_item": "subcontracted_item",
				"work_order": "work_order",
				"batch_no": "batch_no",
				"serial_no": "serial_no",
			},
			"field_no_map": [
				"source_warehouse",
				"expense_account",
				"cost_center",
				"rejected_qty",
				"stock_rejected_qty",
			]
		}

		# Map Packing Slip Items
		for ps_item in source_packing_slip.get("items"):
			if not mapper_item_condition(ps_item, target_doc):
				continue

			target_row = map_child_doc(ps_item, target_doc, packing_slip_item_mapper, source_packing_slip)
			target_row.source_warehouse = source_packing_slip.warehouse

	if len(target_warehouses) == 1 and not target_doc.target_warehouse:
		target_doc.target_warehouse = list(target_warehouses)[0]

	target_doc.run_method("postprocess_after_mapping")
	return target_doc


@frappe.whitelist()
def make_unpack_packing_slip(source_name, target_doc=None):
	def item_condition(source, source_parent, target_parent):
		return bool(flt(source.qty))

	def update_item(source_doc, target_doc, source_parent, target_parent):
		target_doc.qty = -1 * source_doc.qty
		target_doc.source_warehouse = source_parent.warehouse

	def update_material(source_doc, target_doc, source_parent, target_parent):
		target_doc.qty = -1 * source_doc.qty

	def postprocess(source, target):
		target.is_unpack = 1
		target.run_method("postprocess_after_mapping")

	mapper = {
		"Packing Slip": {
			"doctype": "Packing Slip",
			"validation": {
				"docstatus": ["=", 1],
			},
			"field_map": {
				"name": "unpack_against",
				"warehouse": "target_warehouse",
				"package_type": "package_type",
				"purchase_order": "purchase_order",
			},
			"field_no_map": [
				"default_source_warehouse",
			]
		},
		"Packing Slip Item": {
			"doctype": "Packing Slip Item",
			"field_map": {
				"name": "unpack_against_row",
				"source_packing_slip": "source_packing_slip",
				"packing_slip_item": "packing_slip_item",
				"sales_order": "sales_order",
				"sales_order_item": "sales_order_item",
				"purchase_order_item": "purchase_order_item",
				"subcontracted_item": "subcontracted_item",
				"work_order": "work_order",
				"batch_no": "batch_no",
				"serial_no": "serial_no",
			},
			"field_no_map": [
				"rejected_qty",
				"stock_rejected_qty",
				"source_warehouse",
			],
			"condition": item_condition,
			"postprocess": update_item,
		},
		"Packing Slip Packaging Material": {
			"doctype": "Packing Slip Packaging Material",
			"field_map": {
				"name": "unpack_against_row",
				"batch_no": "batch_no",
				"serial_no": "serial_no",
				"source_warehouse": "source_warehouse",
			},
			"postprocess": update_material
		}
	}

	frappe.utils.call_hook_method("update_unpack_from_packing_slip_mapper", mapper)

	unpack_packing_slip = get_mapped_doc("Packing Slip", source_name, mapper, target_doc, postprocess)

	return unpack_packing_slip


@frappe.whitelist()
def make_delivery_note(source_name, target_doc=None, skip_postprocess=False):
	from erpnext.selling.doctype.sales_order.sales_order import (
		make_delivery_note as make_delivery_note_from_sales_order,
		get_item_mapper_for_delivery,
	)

	if isinstance(source_name, str):
		packing_slip_names = [source_name]
	else:
		packing_slip_names = source_name

	# Load Packing Slips and Sales Orders first
	packing_slip_docs = {}
	sales_order_docs = {}
	for ps_name in packing_slip_names:
		packing_slip_doc = packing_slip_docs[ps_name] = frappe.get_doc("Packing Slip", ps_name)
		target_doc = map_target_document("Delivery Note", target_doc, packing_slip_doc)
		for d in packing_slip_doc.get("items"):
			if d.get("sales_order") and not sales_order_docs.get(d.sales_order):
				sales_order_docs[d.sales_order] = frappe.get_doc("Sales Order", d.sales_order)

	# Map Sales Order fields without items
	for sales_order_doc in sales_order_docs.values():
		target_doc = make_delivery_note_from_sales_order(
			sales_order_doc,
			target_doc,
			skip_item_mapping=True,
			skip_postprocess=True,
		)

	# Map Packing Slip Items
	for ps_name in packing_slip_names:
		packing_slip_doc = packing_slip_docs[ps_name]

		so_item_mapper = get_item_mapper_for_delivery(allow_duplicate=True)
		packing_slip_item_mapper = get_packing_slip_item_mapper("Delivery Note Item")

		frappe.utils.call_hook_method("update_delivery_note_from_packing_slip_mapper", so_item_mapper,
			"Sales Order Item")
		frappe.utils.call_hook_method("update_delivery_note_from_packing_slip_mapper", packing_slip_item_mapper,
			"Packing Slip Item")

		for ps_item in packing_slip_doc.get("items"):
			if not mapper_item_condition(ps_item, target_doc):
				continue

			dn_item = None
			if ps_item.get("sales_order_item"):
				so_parent = sales_order_docs[ps_item.sales_order]
				so_item = so_parent.getone("items", {"name": ps_item.sales_order_item})
				if so_item:
					dn_item = map_child_doc(so_item, target_doc, so_item_mapper, so_parent, target_d=dn_item)

			dn_item = map_child_doc(ps_item, target_doc, packing_slip_item_mapper, packing_slip_doc, target_d=dn_item)
			update_mapped_delivery_item(dn_item, packing_slip_doc)

	# Postprocess
	for i, d in enumerate(target_doc.get("items")):
		d.idx = i + 1

	if not cint(skip_postprocess):
		target_doc.run_method("postprocess_after_mapping")

	return target_doc


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None, skip_postprocess=False):
	from erpnext.selling.doctype.sales_order.sales_order import (
		make_sales_invoice as make_sales_invoice_from_sales_order,
		get_item_mapper_for_invoice,
	)

	if isinstance(source_name, str):
		packing_slip_names = [source_name]
	else:
		packing_slip_names = source_name

	# Load Packing Slips and Sales Orders first
	packing_slip_docs = {}
	sales_order_docs = {}
	sales_order_mappers = {}
	for ps_name in packing_slip_names:
		packing_slip_doc = packing_slip_docs[ps_name] = frappe.get_doc("Packing Slip", ps_name)
		target_doc = map_target_document("Sales Invoice", target_doc, packing_slip_doc)
		for d in packing_slip_doc.get("items"):
			if d.get("sales_order") and not sales_order_docs.get(d.sales_order):
				sales_order_docs[d.sales_order] = frappe.get_doc("Sales Order", d.sales_order)
				sales_order_mappers[d.sales_order] = get_item_mapper_for_invoice(d.sales_order, allow_duplicate=True)
				frappe.utils.call_hook_method(
					"update_sales_invoice_from_packing_slip_mapper",
					sales_order_mappers[d.sales_order],
					"Sales Order Item"
				)

		# Map Sales Order fields without items
		for sales_order_doc in sales_order_docs.values():
			target_doc = make_sales_invoice_from_sales_order(
				sales_order_doc,
				target_doc,
				skip_item_mapping=True,
				skip_postprocess=True
			)

	packing_slip_item_mapper = get_packing_slip_item_mapper("Sales Invoice Item")
	frappe.utils.call_hook_method(
		"update_sales_invoice_from_packing_slip_mapper",
		packing_slip_item_mapper,
		"Packing Slip Item",
	)

	# Map Packing Slip Items
	for ps_name in packing_slip_names:
		packing_slip_doc = packing_slip_docs[ps_name]
		for ps_item in packing_slip_doc.get("items"):
			if not mapper_item_condition(ps_item, target_doc):
				continue

			sinv_item = None
			if ps_item.get("sales_order_item"):
				so_parent = sales_order_docs[ps_item.sales_order]
				so_item = so_parent.getone("items", {"name": ps_item.sales_order_item})
				if so_item:
					so_item_mapper = sales_order_mappers[ps_item.sales_order]
					sinv_item = map_child_doc(so_item, target_doc, so_item_mapper, so_parent, target_d=sinv_item)

			sinv_item = map_child_doc(ps_item, target_doc, packing_slip_item_mapper, packing_slip_doc, target_d=sinv_item)
			update_mapped_delivery_item(sinv_item, packing_slip_doc)

	# Post Process
	target_doc.update_stock = 1
	for i, d in enumerate(target_doc.get("items")):
		d.idx = i + 1

	if not cint(skip_postprocess):
		target_doc.run_method("postprocess_after_mapping")
		target_doc.run_method("reset_taxes_and_charges")

	return target_doc


@frappe.whitelist()
def make_stock_entry(source_name, target_doc=None):
	if isinstance(source_name, str):
		packing_slip_names = [source_name]
	else:
		packing_slip_names = source_name

	for ps_name in packing_slip_names:
		packing_slip_doc = frappe.get_doc("Packing Slip", ps_name)
		target_doc = map_target_document("Stock Entry", target_doc, packing_slip_doc)
		map_stock_entry_items(packing_slip_doc, target_doc)

	target_doc.run_method("postprocess_after_mapping")
	return target_doc


def map_stock_entry_items(packing_slip, target_doc, target_warehouse=None):
	packing_slip_item_mapper = get_packing_slip_item_mapper("Stock Entry Detail")
	for ps_item in packing_slip.get("items"):
		if not mapper_item_condition(ps_item, target_doc):
			continue

		ste_item = map_child_doc(ps_item, target_doc, packing_slip_item_mapper, packing_slip)
		ste_item.t_warehouse = target_warehouse or target_doc.to_warehouse
		update_mapped_delivery_item(ste_item, packing_slip, "s_warehouse")


def map_target_document(target_doctype, target_doc, packing_slip):
	if isinstance(target_doc, str):
		target_doc = frappe.get_doc(json.loads(target_doc))

	if not target_doc:
		target_doc = frappe.new_doc(target_doctype)

	if (
		packing_slip.customer and not target_doc.get("customer") and target_doc.meta.has_field("customer")
		and target_doctype != "Stock Entry"
	):
		target_doc.customer = packing_slip.customer

	if packing_slip.supplier and not target_doc.get("supplier") and target_doc.meta.has_field("supplier"):
		target_doc.supplier = packing_slip.supplier
	if packing_slip.purchase_order and target_doc.meta.has_field("purchase_order"):
		target_doc.purchase_order = packing_slip.purchase_order

	if packing_slip.get("cost_center") and not target_doc.get("cost_center") and target_doc.meta.has_field("cost_center"):
		target_doc.cost_center = packing_slip.get("cost_center")

	return target_doc


def mapper_item_condition(ps_item, target_doc):
	if not flt(ps_item.qty):
		return False

	if ps_item.name in [d.packing_slip_item for d in target_doc.get("items") if d.get("packing_slip_item")]:
		return False

	return True


def get_packing_slip_item_mapper(target_doctype):
	return {
		"doctype": target_doctype,
		"field_no_map": [
			"expense_account",
			"cost_center",
		],
		"field_map": {
			"parent": "packing_slip",
			"name": "packing_slip_item",

			"sales_order": "sales_order",
			"sales_order_item": "sales_order_item",

			"subcontracted_item": "subcontracted_item",
			"purchase_order_item": "purchase_order_item",

			"qty": "qty",
			"uom": "uom",
			"conversion_factor": "conversion_factor",
			"net_weight_per_unit": "net_weight_per_unit",

			"batch_no": "batch_no",
			"serial_no": "serial_no",
		}
	}


def update_mapped_delivery_item(target, packing_slip, warehouse_field="warehouse"):
	if target.meta.has_field("weight_uom"):
		target.weight_uom = packing_slip.weight_uom
	if target.meta.has_field(warehouse_field):
		target.set(warehouse_field, packing_slip.warehouse)


@frappe.whitelist()
def reassign_sales_order(packing_slips, sales_order=None):
	if isinstance(packing_slips, str):
		packing_slips = json.loads(packing_slips)

	if not packing_slips:
		frappe.throw(_("Please select Packing Slips to reassign"))

	for name in packing_slips:
		ps_doc = frappe.get_doc("Packing Slip", name)
		ps_doc.check_permission("write")
		ps_doc.reassign_sales_order(sales_order, ignore_permissions=False)

	# Message
	if len(packing_slips) == 1:
		packing_slip_message = frappe.get_desk_link("Packing Slip", packing_slips[0])
	else:
		packing_slip_message = _("{0} Packing Slips").format(len(packing_slips))

	if sales_order:
		frappe.msgprint(
			_("{0} reassigned to {1}").format(
				packing_slip_message,
				frappe.get_desk_link("Sales Order", sales_order)
			), alert=True, indicator="green"
		)
	else:
		frappe.msgprint(
			_("{0} unassigned Sales Order").format(
				packing_slip_message
			), alert=True, indicator="green"
		)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_packing_slips_to_be_delivered(doctype, txt, searchfield, start, page_len, filters, as_dict):
	return _get_packing_slips_to_be_delivered(
		doctype,
		txt,
		searchfield,
		start,
		page_len,
		filters,
		as_dict,
		ignore_permissions=False,
	)


def _get_packing_slips_to_be_delivered(
	doctype="Packing Slip",
	txt="",
	searchfield="name",
	start=0,
	page_len=0,
	filters=None,
	as_dict=True,
	ignore_permissions=True,
):
	fields = get_select_fields_for_packing_slip_query()
	select_fields = ", ".join(["`tabPacking Slip`.{0}".format(f) for f in fields])
	limit = "limit {0}, {1}".format(start, page_len) if page_len else ""

	exists_conditions = []

	no_customer = filters.pop("no_customer", False)
	if no_customer:
		filters["customer"] = ["is", "not set"]

	status_condition = "`tabPacking Slip`.`status` = 'In Stock'"
	include_rejected = filters.pop("include_rejected", False)
	if include_rejected:
		status_condition = "`tabPacking Slip`.`status` in ('In Stock', 'Rejected')"

	if filters.get("sales_order"):
		exists_conditions.append("`tabPacking Slip Item`.sales_order = {0}".format(
			frappe.db.escape(filters.pop("sales_order"))))

	if "sales_order_item" in filters:
		sales_order_items = filters.pop("sales_order_item")
		if sales_order_items:
			if not isinstance(sales_order_items, list):
				sales_order_items = [sales_order_items]

			exists_conditions.append("`tabPacking Slip Item`.sales_order_item in ({0})".format(
				", ".join([frappe.db.escape(i) for i in sales_order_items]),
			))

	if filters.get("item_code"):
		exists_conditions.append("`tabPacking Slip Item`.item_code = {0}".format(
			frappe.db.escape(filters.pop("item_code"))))

	if exists_conditions:
		exists_conditions = """ and exists(select `tabPacking Slip Item`.name from `tabPacking Slip Item` where
				`tabPacking Slip Item`.parent = `tabPacking Slip`.name and {0})""".format(
			" and ".join(exists_conditions))
	else:
		exists_conditions = ""

	return frappe.db.sql("""
			select {fields}
			from `tabPacking Slip`
			where `tabPacking Slip`.`{key}` like {txt}
				and `tabPacking Slip`.docstatus = 1
				and {status_condition}
				{exists_conditions} {fcond} {mcond}
			order by `tabPacking Slip`.posting_date, `tabPacking Slip`.posting_time, `tabPacking Slip`.creation
			{limit}
		""".format(
		fields=select_fields,
		key=searchfield,
		status_condition=status_condition,
		exists_conditions=exists_conditions,
		fcond=get_filters_cond(doctype, filters, [], ignore_permissions=ignore_permissions),
		mcond="" if ignore_permissions else get_match_cond(doctype),
		limit=limit,
		txt="%(txt)s",
	), {"txt": ("%%%s%%" % txt)}, as_dict=as_dict)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_sales_orders_for_reassignment(doctype, txt, searchfield, start, page_len, filters, as_dict):
	return _get_sales_orders_for_reassignment(
		doctype,
		txt,
		searchfield,
		start,
		page_len,
		filters,
		as_dict,
		ignore_permissions=False,
	)


def _get_sales_orders_for_reassignment(
	doctype="Sales Order",
	txt="",
	searchfield="name",
	start=0,
	page_len=0,
	filters=None,
	as_dict=True,
	ignore_permissions=False,
):
	from frappe.desk.reportview import get_filters_cond, get_match_cond
	from erpnext.controllers.queries import get_fields

	if not filters:
		filters = {}
	if not filters.get("packing_slip"):
		frappe.throw(_("Packing Slip not provided"))

	hide_invalid_qty = filters.pop("hide_invalid_qty", 0)

	fields = get_fields(doctype, ["name", "customer", "customer_name", "transaction_date"])
	select_fields = ", ".join(["`tabSales Order`.{0}".format(f) for f in fields])
	limit = "limit {0}, {1}".format(start, page_len) if page_len else ""

	packing_slip = filters.pop("packing_slip")
	ps_doc = frappe.get_doc("Packing Slip", packing_slip)
	if not ps_doc.can_reassign:
		return []

	filters["company"] = ps_doc.get("company")

	items_qty_map = {}
	for d in ps_doc.get("items"):
		key = (cstr(d.item_code), cstr(d.uom))
		items_qty_map.setdefault(key, 0)
		items_qty_map[key] += flt(d.qty)

	if not items_qty_map:
		return []

	qty_precision = frappe.get_precision("Packing Slip Item", "qty")

	item_conditions = []
	for (item_code, uom), qty in items_qty_map.items():
		item_cond = "`tabSales Order Item`.item_code = {item_code} and `tabSales Order Item`.uom = {uom}".format(
			item_code=frappe.db.escape(item_code),
			uom=frappe.db.escape(uom),
		)

		if hide_invalid_qty:
			qty = flt(qty, qty_precision)
			item_cond += f""" and LEAST(
				`tabSales Order Item`.qty - `tabSales Order Item`.delivered_qty,
				`tabSales Order Item`.qty - `tabSales Order Item`.packed_qty,
				`tabSales Order Item`.qty - `tabSales Order Item`.work_order_qty
			) >= {qty}"""

		item_conditions.append(f"""exists(
			select `tabSales Order Item`.name
			from `tabSales Order Item`
			where `tabSales Order Item`.parent = `tabSales Order`.name
				and {item_cond}
				and `tabSales Order Item`.skip_delivery_note = 0
		)""")

	item_conditions_str = " and ".join(item_conditions)

	return frappe.db.sql("""
		select {fields}
		from `tabSales Order`
		where
			`tabSales Order`.docstatus = 1
			and `tabSales Order`.`{key}` like {txt}
			and `tabSales Order`.delivery_status = 'To Deliver'
			and `tabSales Order`.status not in ('Closed', 'On Hold')
			and {item_conditions_str}
			{fcond}
			{mcond}
		order by `tabSales Order`.transaction_date, `tabSales Order`.creation
	""".format(
		fields=select_fields,
		key=searchfield,
		fcond=get_filters_cond(doctype, filters, [], ignore_permissions=ignore_permissions),
		mcond="" if ignore_permissions else get_match_cond(doctype),
		item_conditions_str=item_conditions_str,
		limit=limit,
		txt="%(txt)s",
	), {"txt": ("%%%s%%" % txt)}, as_dict=as_dict)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_packing_slips_for_reassignment(doctype, txt, searchfield, start, page_len, filters, as_dict):
	return _get_packing_slips_for_reassignment(doctype, txt, searchfield, start, page_len, filters, as_dict)


def _get_packing_slips_for_reassignment(
	doctype="Packing Slip",
	txt="",
	searchfield="name",
	start=0,
	page_len=0,
	filters=None,
	as_dict=True,
	ignore_permissions=False,
):
	if not filters:
		filters = {}

	selected_items = filters.pop("selected_items", [])
	if not selected_items:
		return []

	show_reassigned = filters.pop("show_reassigned", 0)
	hide_invalid_qty = filters.pop("hide_invalid_qty", 0)

	fields = get_select_fields_for_packing_slip_query()
	select_fields = ", ".join(["`tabPacking Slip`.{0}".format(f) for f in fields])
	limit = "limit {0}, {1}".format(start, page_len) if page_len else ""

	# Is Reassigned Condition
	is_reassigned_condition = ""
	if not show_reassigned:
		is_reassigned_condition = " and `tabPacking Slip`.is_reassigned = 0"

	# Item Conditions
	items_map = {}
	for d in selected_items:
		key = (cstr(d.get("item_code")), cstr(d.get("uom")))
		item_qtys = items_map.setdefault(key, frappe._dict({
			"qty": 0, "delivered_qty": 0, "packed_qty": 0, "work_order_qty": 0
		}))
		item_qtys.qty += flt(d.get("qty"))
		item_qtys.delivered_qty += flt(d.get("delivered_qty"))
		item_qtys.packed_qty += flt(d.get("packed_qty"))
		item_qtys.work_order_qty += flt(d.get("work_order_qty"))

	exists_conditions = []
	for (item_code, uom), item_qtys in items_map.items():
		cond = "`tabPacking Slip Item`.item_code = {0} and `tabPacking Slip Item`.uom = {1}".format(
			frappe.db.escape(item_code),
			frappe.db.escape(uom),
		)

		if hide_invalid_qty:
			item_qtys.packing_assignable_qty = get_packing_assignable_qty(
				item_qtys.qty, item_qtys.delivered_qty, item_qtys.packed_qty, item_qtys.work_order_qty
			)
			cond += " and `tabPacking Slip Item`.qty <= {0}".format(item_qtys.packing_assignable_qty)

		exists_conditions.append(cond)

	exists_conditions = [f"""exists(select `tabPacking Slip Item`.name from `tabPacking Slip Item` where
		`tabPacking Slip Item`.parent = `tabPacking Slip`.name and {c})""" for c in exists_conditions]

	exists_conditions = " and ".join(exists_conditions)
	exists_conditions = " and " + exists_conditions if exists_conditions else ""

	# Other Filters
	no_customer = filters.pop("no_customer", False)
	if no_customer:
		filters["customer"] = ["is", "not set"]

	return frappe.db.sql("""
			select {fields}
			from `tabPacking Slip`
			where `tabPacking Slip`.`{key}` like {txt}
				and `tabPacking Slip`.docstatus = 1
				and `tabPacking Slip`.status = 'In Stock'
				and `tabPacking Slip`.can_reassign = 1
				{is_reassigned_condition}
				{exists_conditions}
				{fcond}
				{mcond}
			order by `tabPacking Slip`.posting_date, `tabPacking Slip`.posting_time, `tabPacking Slip`.creation
			{limit}
		""".format(
		fields=select_fields,
		key=searchfield,
		is_reassigned_condition=is_reassigned_condition,
		exists_conditions=exists_conditions,
		fcond=get_filters_cond(doctype, filters, [], ignore_permissions=ignore_permissions),
		mcond="" if ignore_permissions else get_match_cond(doctype),
		limit=limit,
		txt="%(txt)s",
	), {"txt": ("%%%s%%" % txt)}, as_dict=as_dict)


def get_packing_assignable_qty(ordered_qty, delivered_qty, packed_qty, work_order_qty):
	undelivered_qty = flt(ordered_qty) - flt(delivered_qty)
	unpacked_qty = flt(ordered_qty) - flt(packed_qty)
	unproducible_qty = flt(ordered_qty) - flt(work_order_qty)

	precision = frappe.get_precision("Sales Order Item", "qty")

	return round_up(
		min(undelivered_qty, unpacked_qty, unproducible_qty),
		precision,
	)


def get_select_fields_for_packing_slip_query():
	return get_fields("Packing Slip", [
		"name", "package_type", "warehouse", "posting_date",
		"customer", "customer_name",
		"total_net_weight", "total_qty", "total_stock_qty",
		"packed_items",
	])
