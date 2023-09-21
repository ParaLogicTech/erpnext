# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erpnext.vehicles.vehicle_transaction_controller import VehicleTransactionController
from erpnext.vehicles.doctype.vehicle_registration_order.vehicle_registration_order import get_vehicle_registration_order


class VehicleNumberPlateReceipt(VehicleTransactionController):
	def validate(self):
		super(VehicleNumberPlateReceipt, self).validate()
		self.validate_duplicate_vehicle()
		self.validate_number_plate_already_received()
		self.set_vehicle_registration_order()
		self.validate_vehicle_registration_order()

	def on_submit(self):
		self.update_vehicle_registration_order()

	def on_cancel(self):
		self.update_vehicle_registration_order()

	def set_missing_values(self, doc=None, for_validate=False):
		for d in self.number_plates:
			self.set_vehicle_booking_order_details(d, for_validate=for_validate)
			self.set_vehicle_details(d, for_validate=for_validate)
			self.set_item_details(d, for_validate=for_validate)

	def validate_duplicate_vehicle(self):
		vehicles = set()
		for d in self.number_plates:
			if d.vehicle:
				if d.vehicle in vehicles:
					frappe.throw(_("Row #{0}: Vehicle {1} is duplicate").format(d.idx, d.vehicle))
				vehicles.add(d.vehicle)

	def validate_number_plate_already_received(self):
		for d in self.number_plates:
			number_plate_received = frappe.db.get_value("Vehicle Number Plate Receipt Detail", filters={
				"vehicle": d.vehicle,
				"docstatus": 1,
				"name": ['!=', d.name]
			}, fieldname="parent")

			if number_plate_received:
				frappe.throw(_("Row #{0}: Number Plate for {1} has already been received in {2}").format(
					d.idx, frappe.get_desk_link("Vehicle", d.vehicle),
					frappe.get_desk_link("Vehicle Number Plate Receipt", number_plate_received)
				))

	def update_vehicle_registration_order(self, doc=None):
		for d in self.number_plates:
			super(VehicleNumberPlateReceipt, self).update_vehicle_registration_order(d)

	def validate_vehicle_item(self, doc=None):
		for d in self.number_plates:
			super(VehicleNumberPlateReceipt, self).validate_vehicle_item(d)

	def validate_vehicle(self, doc=None):
		for d in self.number_plates:
			super(VehicleNumberPlateReceipt, self).validate_vehicle(d)

	def validate_vehicle_booking_order(self, doc=None):
		for d in self.number_plates:
			super(VehicleNumberPlateReceipt, self).validate_vehicle_booking_order(d)

	def set_vehicle_registration_order(self):
		for d in self.number_plates:
			d.vehicle_registration_order = get_vehicle_registration_order(d.vehicle)

	def validate_vehicle_registration_order(self):
		for d in self.number_plates:
			if not d.vehicle_registration_order:
				frappe.throw(_("Row #{0}: Vehicle Registration Order is mandatory").format(d.idx))
			if not frappe.db.get_value("Vehicle Registration Order", d.vehicle_registration_order, "vehicle_license_plate"):
				frappe.throw(_("Row #{0}: Registration for {1} is not yet complete").format(
					d.idx,
					frappe.get_desk_link("Vehicle Registration Order", d.vehicle_registration_order)
				))

			super(VehicleNumberPlateReceipt, self).validate_vehicle_registration_order(d)
