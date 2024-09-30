# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cstr, combine_datetime, get_datetime
from erpnext.vehicles.vehicle_transaction_controller import VehicleTransactionController
from erpnext.maintenance.doctype.maintenance_schedule.maintenance_schedule import schedule_next_project_template


class VehicleGatePass(VehicleTransactionController):
	def get_feed(self):
		return _("For {0} | {1}").format(self.get("customer_name") or self.get('customer'),
			self.get("item_name") or self.get("item_code"))

	def validate(self):
		self.validate_purpose_based_mandatory_fields()
		self.validate_purpose_based_permissions()
		super(VehicleGatePass, self).validate()
		self.validate_duplicate_gate_pass()
		self.validate_vehicle_delivery()
		self.validate_opportunity()
		self.validate_vehicle_received()
		self.validate_sales_invoice()
		self.set_invoice_is_unpaid()
		self.validate_project_ready_to_close()
		self.set_title()

	def before_submit(self):
		self.validate_vehicle_mandatory()

	def on_submit(self):
		self.update_project_vehicle_status()
		self.make_vehicle_log()
		self.add_vehicle_maintenance_schedule()

	def on_cancel(self):
		self.update_project_vehicle_status()
		self.cancel_vehicle_log()
		self.remove_vehicle_maintenance_schedule()

	def set_title(self):
		self.title = self.get('customer_name') or self.get('customer')

	def set_missing_values(self, doc=None, for_validate=False):
		self.set_vehicle_delivery_details()
		self.set_opportunity_details()
		super().set_missing_values(self, for_validate)

	def set_opportunity_details(self):
		if not self.get("opportunity"):
			return

		opportunity_details = get_opportunity_details(self.opportunity)
		for k, v in opportunity_details.items():
			if self.meta.has_field(k) and (not self.get(k)):
				self.set(k, v)

	def set_vehicle_delivery_details(self):
		if not self.get("vehicle_delivery"):
			return

		vehicle_delivery_details = get_vehicle_delivery_details(self.vehicle_delivery)
		for k, v in vehicle_delivery_details.items():
			if self.meta.has_field(k) and (not self.get(k)):
				self.set(k, v)

	def validate_purpose_based_mandatory_fields(self):
		# Service fields cleanup
		if self.purpose not in ("Service - Vehicle Delivery", "Service - Test Drive"):
			self.project = None
			self.project_workshop = None
			self.service_advisor = None

		if self.purpose != "Service - Vehicle Delivery":
			self.sales_invoice = None

		if self.purpose != "Service - Test Drive":
			self.technician = None

		# Sales fields cleanup
		if self.purpose not in ("Sales - Test Drive", "Sales - Vehicle Delivery"):
			self.sales_person = None

		if self.purpose != "Sales - Vehicle Delivery":
			self.vehicle_booking_order = None
			self.vehicle_delivery = None

		if self.purpose != "Sales - Test Drive":
			self.lead = None
			self.opportunity = None

		if self.purpose == "Sales - Test Drive" and self.lead:
			self.customer = None

		# Validate Mandatory
		if not self.get("customer") and self.purpose != "Sales - Test Drive":
			frappe.throw(_("Customer is mandatory"))
		if not self.get("customer") and not self.get("lead"):
			frappe.throw(_("Customer or Lead is mandatory").format(self.purpose))

		if self.purpose in ["Service - Vehicle Delivery", "Service - Test Drive"]:
			if not self.get("project"):
				frappe.throw(_("Repair Order is mandatory for Purpose {0}.").format(self.purpose))
			if not self.get("project_workshop"):
				frappe.throw(_("Project Workshop is mandatory for Purpose {0}.").format(self.purpose))

		if self.purpose == "Sales - Vehicle Delivery":
			if not self.vehicle_delivery:
				frappe.throw(_("Vehicle Delivery is mandatory for Purpose {0}.").format(self.purpose))

	def validate_purpose_based_permissions(self):
		purpose_permission_field_map = {
			"Sales - Test Drive": "restrict_sales_test_drive_gate_pass_to_role",
			"Sales - Vehicle Delivery": "restrict_sales_delivery_gate_pass_to_role",
			"Service - Test Drive": "restrict_service_test_drive_gate_pass_to_role",
			"Service - Vehicle Delivery": "restrict_service_delivery_gate_pass_to_role",
		}

		role_field = purpose_permission_field_map.get(self.purpose)

		role_allowed = frappe.get_cached_value("Vehicles Settings", None, role_field)
		if role_allowed and role_allowed not in frappe.get_roles():
			frappe.throw("Not allowed to create Vehicle Gate Pass for {0}".format(self.purpose))

	def validate_duplicate_gate_pass(self):
		if self.purpose in ("Service - Vehicle Delivery", "Sales - Vehicle Delivery"):
			filters = {
				"purpose": self.purpose,
				"vehicle": self.vehicle,
				"docstatus": 1,
				"name": ['!=', self.name]
			}

			if self.purpose == "Service - Vehicle Delivery":
				filters["project"] = self.project
			elif self.purpose == "Sales - Vehicle Delivery":
				filters["vehicle_delivery"] = self.vehicle_delivery

			existing_gate_pass = frappe.db.get_value("Vehicle Gate Pass", filters=filters)
			if existing_gate_pass:
				frappe.throw(_("{0} Gate Pass already exists {1}").format(
					self.purpose,
					frappe.get_desk_link("Vehicle Gate Pass", existing_gate_pass))
				)

		if self.get('sales_invoice'):
			existing_gate_pass = frappe.db.get_value("Vehicle Gate Pass", filters={
				"sales_invoice": self.sales_invoice,
				"vehicle": self.vehicle,
				"docstatus": 1,
				"name": ['!=', self.name]
			})

			if existing_gate_pass:
				frappe.throw(_("Vehicle Gate Pass for {0} already exists in {1}")
					.format(frappe.get_desk_link("Sales Invoice", self.sales_invoice),
					frappe.get_desk_link("Vehicle Gate Pass", existing_gate_pass)))

	def validate_vehicle_delivery(self):
		if self.get("vehicle_delivery"):
			vehicle_delivery = frappe.db.get_value("Vehicle Delivery", self.vehicle_delivery, [
				'docstatus', 'customer', 'item_code', 'vehicle', 'is_return',
			], as_dict=1)

			if not vehicle_delivery:
				frappe.throw(_("Vehicle Delivery {0} does not exist").format(self.vehicle_delivery))

			if vehicle_delivery.docstatus != 1:
				frappe.throw(_("{0} is not submitted").format(
					frappe.get_desk_link("Vehicle Delivery", self.vehicle_delivery))
				)

			if vehicle_delivery.is_return:
				frappe.throw(_("Cannot create a Vehicle Gate Pass against a Delivery Return"))

			if self.customer != vehicle_delivery.customer:
				frappe.throw(_("Customer does not match in {0}")
					.format(frappe.get_desk_link("Vehicle Delivery", self.vehicle_delivery)))

			if self.item_code != vehicle_delivery.item_code:
				frappe.throw(_("Variant Item Code does not match in {0}")
					.format(frappe.get_desk_link("Vehicle Delivery", self.vehicle_delivery)))

			if self.vehicle != vehicle_delivery.vehicle:
				frappe.throw(_("Vehicle does not match in {0}")
					.format(frappe.get_desk_link("Vehicle Delivery", self.vehicle_delivery)))

	def validate_opportunity(self):
		if self.get("opportunity"):
			opportunity = frappe.db.get_value("Opportunity", self.opportunity, [
				'opportunity_from', 'party_name',
			], as_dict=1)

			if not opportunity:
				frappe.throw(_("Opportunity {0} does not exist").format(self.opportunity))

			if opportunity.opportunity_from == "Customer":
				if self.customer != opportunity.party_name:
					frappe.throw(_("Customer does not match in {0}").format(
						frappe.get_desk_link("Opportunity", self.opportunity))
					)
			else:
				if self.lead != opportunity.party_name:
					frappe.throw(_("Lead does not match in {0}").format(
						frappe.get_desk_link("Opportunity", self.opportunity))
					)

	def validate_sales_invoice(self):
		if self.get('sales_invoice'):
			sales_invoice = frappe.db.get_value("Sales Invoice", self.sales_invoice, ['name', 'docstatus', 'project'],
				as_dict=1)
			if not sales_invoice:
				frappe.throw(_("Sales Invoice {0} does not exist").format(sales_invoice.name))

			if cstr(sales_invoice.project) != cstr(self.project):
				frappe.throw(_("Repair Order does not match in {0}")
					.format(frappe.get_desk_link("Sales Invoice", sales_invoice.name)))

			if self.docstatus == 1:
				if sales_invoice.docstatus != 1:
					frappe.throw(_("Sales Invoice {0} is not submitted").format(sales_invoice.name))
			else:
				if sales_invoice.docstatus == 2:
					frappe.throw(_("Sales Invoice {0} is cancelled").format(sales_invoice.name))

	def validate_project_ready_to_close(self):
		if self.purpose != "Service - Vehicle Delivery":
			return

		if not frappe.db.get_value('Project', self.project, 'ready_to_close'):
			frappe.throw(_("{0} is not Ready to Close").format(frappe.get_desk_link("Project", self.project)))

	def validate_vehicle_received(self):
		if self.purpose == "Service - Vehicle Delivery":
			vehicle_service_receipt = frappe.db.get_value("Vehicle Service Receipt",
				fieldname=['name', 'timestamp(posting_date, posting_time) as posting_dt'],
				filters={"project": self.project, "vehicle": self.vehicle, "project_workshop": self.project_workshop,
					"docstatus": 1},
				order_by='posting_date, posting_time, creation', as_dict=1)

			if vehicle_service_receipt:
				self_posting_dt = combine_datetime(self.posting_date, self.posting_time)
				if self_posting_dt < get_datetime(vehicle_service_receipt.posting_dt):
					frappe.throw(_("Vehicle Gate Pass Delivery Date/Time cannot be before Received Date/Time {0}").format(
						frappe.bold(frappe.format(vehicle_service_receipt.posting_dt)))
					)
			else:
				frappe.throw(_("Vehicle has not been received in Project Workshop {0} for {1} yet").format(
					self.project_workshop, frappe.get_desk_link("Project", self.project))
				)

		if self.purpose == "Sales - Test Drive":
			vehicle_details = frappe.db.get_value("Vehicle", self.vehicle,
				["purchase_document_no", "delivery_document_no"], as_dict=1)

			if not vehicle_details:
				frappe.throw(_("Vehicle {0} does not exist").format(self.vehicle))
			if not vehicle_details.purchase_document_no or vehicle_details.delivery_document_no:
				frappe.throw(_("Vehicle is not in stock"))

		if self.purpose == "Sales - Vehicle Delivery":
			if not frappe.db.get_value("Vehicle", self.vehicle, "delivery_document_no"):
				frappe.throw(_("Vehicle has not been delivered yet"))

	def add_vehicle_maintenance_schedule(self):
		if self.get("project"):
			project = frappe.get_doc("Project", self.project).as_dict()
			serial_no = self.vehicle

			args = frappe._dict({
				'reference_name': project.name,
				'reference_doctype': project.doctype,
				'reference_date': project.project_date,
				'customer': project.customer,
				'customer_name': project.customer_name,
				'contact_person': project.contact_person,
				'contact_display': project.contact_display,
				'contact_mobile': project.contact_mobile,
				'contact_phone': project.contact_phone,
				'contact_email': project.contact_email
			})

			for template in project.project_templates:
				schedule_next_project_template(template.project_template, serial_no, args)

	def remove_vehicle_maintenance_schedule(self, reference_doctype=None, reference_name=None):
		if self.get("project"):
			return super().remove_vehicle_maintenance_schedule("Project", self.project)
	
	def set_invoice_is_unpaid(self):
		if self.get("sales_invoice"):
			sales_invoice = frappe.db.get_value("Sales Invoice", self.sales_invoice, ['outstanding_amount', 'docstatus'],
				as_dict=1)
			if sales_invoice.outstanding_amount > 0 and sales_invoice.docstatus == 1:
				self.invoice_is_unpaid = 1
			else:
				self.invoice_is_unpaid = 0
		else:
			self.invoice_is_unpaid = 0


@frappe.whitelist()
def get_opportunity_details(opportunity):
	if not opportunity:
		frappe.throw(_("Opportunity not provided"))

	doc = frappe.get_doc("Opportunity", opportunity)

	out = frappe._dict()
	if doc.opportunity_from == "Lead":
		out.lead = doc.party_name
		out.customer = None
	else:
		out.customer = doc.party_name
		out.lead = None

	out.item_code = doc.applies_to_item
	out.item_name = doc.applies_to_item_name
	out.vehicle = doc.get("applies_to_vehicle")
	out.sales_person = doc.sales_person

	return out


@frappe.whitelist()
def get_vehicle_delivery_details(vehicle_delivery):
	if not vehicle_delivery:
		frappe.throw(_("Vehicle Delivery not provided"))

	vehicle_delivery_details = frappe.db.get_value("Vehicle Delivery", vehicle_delivery, [
		"vehicle_booking_order", "vehicle", "item_code", "item_name",
		"customer", "contact_person", "customer_address",
	], as_dict=1)

	return vehicle_delivery_details or {}
