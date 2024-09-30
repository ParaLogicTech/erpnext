# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erpnext.vehicles.vehicle_transaction_controller import VehicleTransactionController
from frappe.utils import cint


class VehicleServiceReceipt(VehicleTransactionController):
	def get_feed(self):
		return _("From {0} | {1}").format(self.get("customer_name") or self.get('customer'),
			self.get("item_name") or self.get("item_code"))

	def validate(self):
		super(VehicleServiceReceipt, self).validate()
		self.validate_duplicate_receipt()
		self.validate_project_mandatory_values()
		self.set_title()

	def before_submit(self):
		self.validate_vehicle_mandatory()

	def on_submit(self):
		self.update_project_vehicle_status()
		self.make_vehicle_log()

	def before_cancel(self):
		self.validate_already_delivered()

	def on_cancel(self):
		self.update_project_vehicle_status()
		self.cancel_vehicle_log()

	def set_missing_values(self, doc=None, for_validate=False):
		super().set_missing_values(doc=None, for_validate=False)
		self.set_service_cr_details()

	def set_title(self):
		self.title = self.get('customer_name') or self.get('customer')

	def set_service_cr_details(self):
		self.service_cr = frappe.db.get_single_value('Vehicles Settings', 'default_service_cr')

		service_cr = frappe.get_cached_doc("Employee", self.service_cr) if self.service_cr else frappe._dict()
		self.service_cr_name = service_cr.employee_name
		self.service_cr_contact_no = service_cr.cell_number

	def validate_duplicate_receipt(self):
		if self.get('project'):
			project_vehicle_service_receipt = frappe.db.get_value("Vehicle Service Receipt",
				filters={"project": self.project, "vehicle": self.vehicle, "docstatus": 1, "name": ['!=', self.name]})

			if project_vehicle_service_receipt:
				frappe.throw(_("Vehicle Service Receipt for {0} already exists in {1}")
					.format(frappe.get_desk_link("Project", self.project),
					frappe.get_desk_link("Vehicle Gate Pass", project_vehicle_service_receipt)))

	def validate_already_delivered(self):
		project_gate_pass = frappe.db.get_value("Vehicle Gate Pass",
			filters={"project": self.project, "vehicle": self.vehicle, "docstatus": 1})

		if project_gate_pass:
			frappe.throw(_("Cannot cancel because Vehicle Gate Pass for {0} already exists in {1}")
				.format(frappe.get_desk_link("Project", self.project),
				frappe.get_desk_link("Vehicle Gate Pass", project_gate_pass)))

	def validate_project_mandatory_values(self):
		if not self.project:
			return

		project = frappe.db.get_value("Project", self.project,
			['vehicle_unregistered', 'vehicle_license_plate', 'fuel_level', 'vehicle_first_odometer'], as_dict=1)

		if not project:
			frappe.throw(_("Project {0} does not exist").format(self.project))

		if cint(frappe.db.get_single_value("Vehicles Settings", "fuel_level_required_for_service_receipt")):
			if not project.fuel_level:
					frappe.throw(_("Fuel Level is mandatory in {0} to make Vehicle Service Receipt")
						.format(frappe.get_desk_link("Project", self.project)))

		if cint(frappe.db.get_single_value("Vehicles Settings", "odometer_reading_required_for_service_receipt")):
			if not project.vehicle_first_odometer:
				frappe.throw(_("First Odometer Reading is mandatory in {0} to make Vehicle Service Receipt")
					.format(frappe.get_desk_link("Project", self.project)))

		if cint(frappe.db.get_single_value("Vehicles Settings", "license_plate_required_for_service_receipt")):
			if not project.vehicle_unregistered and not project.vehicle_license_plate:
				frappe.throw(_("Vehicle License Plate is mandatory in {0} to make Vehicle Service Receipt")
					.format(frappe.get_desk_link("Project", self.project)))
				