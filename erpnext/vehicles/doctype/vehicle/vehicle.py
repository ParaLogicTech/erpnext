# -*- coding: utf-8 -*-
# Copyright (c) 2024, ParaLogic and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, cstr, cint
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from erpnext.vehicles.utils import format_vehicle_id
from erpnext.maintenance.doctype.maintenance_schedule.maintenance_schedule import get_maintenance_schedule_from_serial_no
from erpnext.vehicles.doctype.vehicle_log.vehicle_log import get_vehicle_odometer


class Vehicle(Document):
	_copy_fields = [
		'company',
		'warehouse', 'sales_order',
		'customer', 'customer_name',
		'is_reserved', 'reserved_customer', 'reserved_customer_name',
		'supplier', 'supplier_name',
		'purchase_document_type', 'purchase_document_no', 'purchase_date', 'purchase_time', 'purchase_rate',
		'delivery_document_type', 'delivery_document_no', 'delivery_date', 'delivery_time', 'sales_invoice',
		'warranty_status',
	]

	_sync_fields = [
		'item_code',
		'customer', 'customer_name',
		'is_reserved', 'reserved_customer', 'reserved_customer_name',
		'vehicle_owner', 'vehicle_owner_name',
		'sales_order', 'delivery_date',
		'warranty_expiry_date',
	]

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.via_stock_ledger = False

	def autoname(self):
		if self.flags.from_serial_no:
			self.name = self.flags.from_serial_no
		else:
			item = frappe.get_cached_doc("Item", self.item_code)
			serial_no_series = item.serial_no_series
			if serial_no_series:
				self.name = make_autoname(serial_no_series, "Serial No", item)

	def onload(self):
		self.copy_image_from_item()
		self.set_onload('stock_exists', self.stock_ledger_created())
		self.set_onload('cant_change_fields', self.get_cant_change_fields())
		self.set_onload('cant_change_customer', self.cant_change_customer())

		if not self.is_new():
			self.set_onload('maintenance_schedule_data', get_maintenance_schedule_from_serial_no(serial_no=self.name))

	def validate(self):
		self.validate_item()
		self.validate_vehicle_id()
		self.validate_duplicate_vehicle()
		self.copy_image_from_item()

		self.sync_with_serial_no()

		self.set_status()

		self.validate_cant_change()

	def on_update(self):
		self.create_vehicle_serial_no()
		self.db_set("last_odometer", get_vehicle_odometer(self.name))

	def on_trash(self):
		self.delete_serial_no_on_trash()

	def delete_serial_no_on_trash(self):
		if frappe.db.exists("Serial No", self.name):
			frappe.delete_doc("Serial No", self.name, ignore_permissions=True)

	def copy_image_from_item(self):
		if not self.image:
			self.image = frappe.get_cached_value('Item', self.item_code, 'image')

	def validate_item(self):
		item = frappe.get_cached_doc("Item", self.item_code)
		if not item.is_vehicle:
			frappe.throw(_("Item {0} is not setup as a Vehicle Item").format(self.item_code))

		self.update(get_vehicle_make_model(self.item_code))
		self.item_group = item.item_group
		self.warranty_period = item.warranty_period

	def validate_vehicle_id(self):
		if self.unregistered:
			self.plate_region = None
			self.license_plate = ""

		# Format/Clean
		self.chassis_no = format_vehicle_id(self.chassis_no)
		self.engine_no = format_vehicle_id(self.engine_no)
		self.license_plate = format_vehicle_id(self.license_plate)

		if self.plate_region:
			plate_region_doc = frappe.get_cached_doc("Vehicle Plate Region", self.plate_region)
			plate_region_doc.validate_license_plate(self.license_plate, self.item_code)

	def validate_duplicate_vehicle(self):
		exclude = None if self.is_new() else self.name
		validate_duplicate_vehicle('chassis_no', self.chassis_no, exclude=exclude, throw=True)
		validate_duplicate_vehicle('engine_no', self.engine_no, exclude=exclude, throw=True)
		validate_duplicate_vehicle('license_plate', self.license_plate, exclude=exclude, throw=True)

	def sync_with_serial_no(self, serial_no_doc=None):
		if not serial_no_doc:
			serial_no_doc = self.get_serial_no_doc()

		if not serial_no_doc:
			return

		serial_no_doc.flags.allow_change_item_code = True

		before_values_sync = frappe.db.get_value(self.doctype, self.name, self._sync_fields, as_dict=1)
		to_sync = any([before_values_sync.get(key) != self.get(key) for key in before_values_sync])

		if to_sync:
			for key in self._sync_fields:
				serial_no_doc.set(key, self.get(key))

			serial_no_doc.flags.from_vehicle = self.name
			serial_no_doc.save(ignore_permissions=1)

		for f in self._copy_fields:
			self.set(f, serial_no_doc.get(f))

	def get_serial_no_doc(self):
		serial_no_doc = None
		if self.flags.from_serial_no:
			serial_no_doc = frappe.get_cached_doc("Serial No", self.flags.from_serial_no)
		else:
			serial_no_name = frappe.db.get_value("Serial No", {"vehicle": self.name}, "name")
			if serial_no_name:
				serial_no_doc = frappe.get_doc("Serial No", serial_no_name)

		return serial_no_doc

	def create_vehicle_serial_no(self):
		if self.flags.from_serial_no:
			serial_no_doc = frappe.get_cached_doc("Serial No", self.flags.from_serial_no)
			serial_no_doc.db_set('vehicle', self.name)
		else:
			if not frappe.db.exists("Serial No", self.name):
				serial_no_doc = frappe.new_doc("Serial No")
				serial_no_doc.flags.from_vehicle = self.name

				for fieldname in self._copy_fields:
					serial_no_doc.set(fieldname, self.get(fieldname))

				serial_no_doc.item_code = self.item_code
				serial_no_doc.serial_no = self.name
				serial_no_doc.vehicle = self.name
				serial_no_doc.insert(ignore_permissions=True)

				self.sync_with_serial_no(serial_no_doc)
				self.db_update()

	def set_status(self):
		if self.delivery_document_type:
			self.status = "Delivered"
		elif self.warranty_expiry_date and getdate(self.warranty_expiry_date) <= getdate(nowdate()):
			self.status = "Expired"
		elif not self.warehouse:
			self.status = "Inactive"
		else:
			self.status = "Active"

	def validate_cant_change(self):
		if self.is_new():
			return

		fields = self.get_cant_change_fields()
		cant_change_fields = [f for f, cant_change in fields.items() if cant_change]

		if cant_change_fields:
			previous_values = frappe.db.get_value(self.doctype, self.name, cant_change_fields, as_dict=1)
			for f, old_value in previous_values.items():
				if cstr(self.get(f)) != cstr(old_value):
					label = self.meta.get_label(f)
					frappe.throw(_("Cannot change {0} because transactions already exists for this Vehicle")
						.format(frappe.bold(label)))

	def get_cant_change_fields(self):
		ledger_or_invoice_exists = self.stock_ledger_created()
		return frappe._dict({
			'brand': ledger_or_invoice_exists,
			'item_code': ledger_or_invoice_exists,
			'variant_of': ledger_or_invoice_exists,
			'chassis_no': ledger_or_invoice_exists,
		})

	def stock_ledger_created(self):
		if not hasattr(self, '_stock_ledger_created'):
			self._stock_ledger_created = len(frappe.db.sql("""
				select name
				from `tabStock Ledger Entry`
				where exists(select sr.name from `tabStock Ledger Entry Serial No` sr
					where sr.parent = `tabStock Ledger Entry`.name and sr.serial_no = %s)
				limit 1
			""", self.name))
		return self._stock_ledger_created

	def cant_change_customer(self):
		serial_no_doc = self.get_serial_no_doc()
		return serial_no_doc.cant_change_customer() if serial_no_doc else True


def split_vehicle_items_by_qty(doc):
	new_rows = []
	for d in doc.items:
		new_rows.append(d)
		if d.qty > 1 and d.item_code and frappe.get_cached_value("Item", d.item_code, "is_vehicle"):
			qty = cint(d.qty)
			d.qty = 1

			for i in range(qty - 1):
				new_rows.append(frappe.copy_doc(d))

	doc.items = new_rows
	for i, d in enumerate(doc.items):
		d.idx = i + 1


@frappe.whitelist()
def validate_duplicate_vehicle(fieldname, value, exclude=None, throw=False):
	if not value:
		return

	meta = frappe.get_meta("Vehicle")
	if not fieldname or not meta.has_field(fieldname):
		frappe.throw(_("Invalid fieldname {0}").format(fieldname))

	label = _(meta.get_field(fieldname).label)

	filters = {fieldname: value}
	if exclude:
		filters['name'] = ['!=', exclude]

	duplicates = frappe.db.get_all("Vehicle", filters=filters)
	duplicate_names = [d.name for d in duplicates]
	if duplicates:
		frappe.msgprint(_("{0} {1} is already set in Vehicle: {2}").format(label, frappe.bold(value),
			", ".join([frappe.utils.get_link_to_form("Vehicle", name) for name in duplicate_names])),
			raise_exception=throw, indicator='red' if throw else 'orange')


@frappe.whitelist()
def warn_vehicle_reserved(vehicle, customer=None, throw=False):
	vehicle_details = frappe.db.get_value("Vehicle", vehicle,
		['is_reserved', 'reserved_customer', 'reserved_customer_name'], as_dict=1)

	if not vehicle_details:
		return

	if cint(vehicle_details.is_reserved):
		if vehicle_details.reserved_customer:
			if vehicle_details.reserved_customer != customer:
				frappe.msgprint(_("{0} is reserved for Customer {1}").format(
					frappe.get_desk_link("Vehicle", vehicle),
					frappe.bold(vehicle_details.reserved_customer_name or vehicle_details.reserved_customer)),
				title="Reserved", indicator="red" if throw else "orange", raise_exception=throw)
		else:
			frappe.msgprint(_("{0} is reserved without a Customer").format(frappe.get_desk_link("Vehicle", vehicle)),
				title="Reserved", indicator="orange")


@frappe.whitelist()
def warn_vehicle_reserved_by_sales_person(vehicle, sales_person=None, throw=False):
	vehicle_details = frappe.db.get_value("Vehicle", vehicle,
		['is_reserved', 'reserved_sales_person'], as_dict=1)

	if not vehicle_details or not vehicle_details.is_reserved:
		return

	if vehicle_details.reserved_sales_person and vehicle_details.reserved_sales_person != sales_person:
		frappe.msgprint(_("Vehicle {0} is reserved by Sales Person {1}").format(
			frappe.get_desk_link("Vehicle", vehicle),
			frappe.bold(vehicle_details.reserved_sales_person)
		), title="Reserved", indicator="red" if throw else "orange", raise_exception=throw)


@frappe.whitelist()
def get_vehicle_make_model(item_code):
	out = frappe._dict({
		"item_name": None,
		"variant_of": None,
		"variant_of_name": None,
		"brand": None,
	})
	if not item_code:
		return out

	details = frappe.get_cached_value("Item", item_code, [
		"item_name", "variant_of", "brand"
	], as_dict=1)
	if details:
		details.variant_of = details.variant_of or item_code
		details.variant_of_name = frappe.get_cached_value("Item", details.variant_of, "item_name") if details.variant_of else None
		out.update(details)

	return out


@frappe.whitelist()
def get_vehicle_image(vehicle=None, item_code=None):
	image = None

	if vehicle:
		vehicle_details = frappe.db.get_value("Vehicle", vehicle, ['item_code', 'image'], as_dict=1)
		if vehicle_details:
			item_code = vehicle_details.item_code
			image = vehicle_details.image

	if not image and item_code:
		image = frappe.get_cached_value("Item", item_code, 'image')

	return image


def get_vehicle_from_serial_no(serial_no):
	if not serial_no:
		return None

	return frappe.db.get_value("Serial No", serial_no, "vehicle", cache=1)
