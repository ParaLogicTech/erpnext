# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erpnext.vehicles.vehicle_transaction_controller import VehicleTransactionController
from erpnext.vehicles.doctype.vehicle.vehicle import warn_vehicle_reserved, warn_vehicle_reserved_by_sales_person

class VehicleTransferLetter(VehicleTransactionController):
	def get_feed(self):
		return _("To {0} | {1}").format(self.get("customer_name") or self.get('customer'),
			self.get("item_name") or self.get("item_code"))

	def validate(self):
		super(VehicleTransferLetter, self).validate()
		self.validate_same_owner()
		self.set_vehicle_registration_order()
		self.validate_vehicle_registration_order()
		self.validate_vehicle_reservation()

		self.set_title()

	def before_submit(self):
		self.validate_vehicle_mandatory()

	def on_submit(self):
		self.update_vehicle_booking_order_transfer_customer()
		self.update_vehicle_booking_order_transfer()
		self.make_vehicle_log()

	def on_cancel(self):
		self.update_vehicle_booking_order_transfer_customer()
		self.update_vehicle_booking_order_transfer()
		self.cancel_vehicle_log()

	def validate_same_owner(self):
		if self.customer == self.vehicle_owner:
			frappe.throw(_("New Owner and Previous Owner cannot be the same"))

	def validate_vehicle_reservation(self):
		throw = self.docstatus == 1
		warn_vehicle_reserved(self.vehicle, self.customer, throw=throw)
		warn_vehicle_reserved_by_sales_person(self.vehicle, self.sales_person, throw=throw)

	def set_title(self):
		self.title = "{0} / {1}".format(self.customer_name or self.customer, self.get_previous_owner_name())

	def get_previous_owner_name(self):
		return self.get('booking_customer_name') or self.get('vehicle_owner_name') \
			or self.get('vehicle_owner') or self.get('company')
