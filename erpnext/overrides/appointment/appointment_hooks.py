import frappe
import erpnext
from frappe import _
from frappe.utils import strip_html
from crm.crm.doctype.appointment.appointment import Appointment
from erpnext.overrides.lead.lead_hooks import get_customer_from_lead
from erpnext.stock.get_item_details import get_applies_to_details, get_force_applies_to_fields
from frappe.model.mapper import get_mapped_doc


class AppointmentERP(Appointment):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.force_applies_to_fields = get_force_applies_to_fields(self.doctype)

	def onload(self):
		super().onload()
		self.set_onload('customer', self.get_customer())

	def before_print(self, print_settings=None):
		self.company_address_doc = erpnext.get_company_address_doc(self)

	def validate(self):
		super().validate()
		self.validate_sales_order()

	@classmethod
	def get_allowed_party_types(cls):
		return super().get_allowed_party_types() + ["Customer"]

	def set_missing_values(self):
		super().set_missing_values()
		self.set_applies_to_details()
		self.set_service_template_details()

	def validate_sales_order(self):
		if not self.get("sales_order"):
			return

		so_details = frappe.db.get_value("Sales Order", self.sales_order, [
			"customer", "company", "docstatus", "billing_status",
		], as_dict=1)

		if not so_details:
			frappe.throw(_("Sales Order {0} does not exist").format(self.sales_order))

		if so_details.docstatus != 1:
			frappe.throw(_("{0} is not submitted").format(
				frappe.get_desk_link("Sales Order", self.sales_order)
			))

		if so_details.billing_status != "To Bill":
			frappe.throw(_("{0} is not billable").format(
				frappe.get_desk_link("Sales Order", self.sales_order)
			))

		if self.company != so_details.company:
			frappe.throw(_("Company {0} does not match with {1} Company {2}").format(
				frappe.bold(self.company),
				frappe.get_desk_link("Sales Order", self.sales_order),
				frappe.bold(so_details.company),
			))

		if self.party_name != so_details.customer or self.appointment_for != "Customer":
			frappe.throw(_("Customer {0} does not match with {1} Customer {2}").format(
				frappe.bold(self.party_name),
				frappe.get_desk_link("Sales Order", self.sales_order),
				frappe.bold(so_details.customer),
			))

	def set_missing_values_after_submit(self):
		super().set_missing_values_after_submit()
		self.set_applies_to_details()

	def validate_next_document_on_cancel(self):
		super().validate_next_document_on_cancel()
		project = self.get_linked_projects()
		if project:
			frappe.throw(_("Cannot cancel appointment because it is closed by {0}").format(
				frappe.get_desk_link("Project", project)
			))

	def set_applies_to_details(self):
		args = self.as_dict()
		applies_to_details = get_applies_to_details(args, for_validate=True)

		for k, v in applies_to_details.items():
			if self.meta.has_field(k) and not self.get(k) or k in self.force_applies_to_fields:
				self.set(k, v)

	def set_service_template_details(self):
		for row in self.service_templates:
			if row.service_template and not row.service_template_name:
				row.service_template_name = frappe.get_cached_value(
					"Service Template",
					row.service_template,
					"service_template_name",
				)

	def get_customer(self, throw=False):
		if self.appointment_for == "Customer":
			return self.party_name
		elif self.appointment_for == "Lead":
			return get_customer_from_lead(self.party_name, throw=throw)
		else:
			return None

	def link_with_opportunity(self, opportunity):
		super().link_with_opportunity(opportunity)

		projects = self.get_linked_projects()
		for name in projects:
			project_doc = frappe.get_doc("Project", name, for_update=True)
			project_doc.load_doc_before_save()

			project_doc.opportunity = opportunity
			if self.sales_person:
				project_doc.sales_person = self.sales_person
				project_doc.set_sales_person_details()

			project_doc.set_user_and_timestamp()
			project_doc.db_update()
			project_doc.save_version()
			project_doc.notify_update()

			project_doc.reassign_sales_person_in_sales_transactions()

	def is_appointment_converted(self):
		return super().is_appointment_converted() or self.get_linked_projects()

	def get_linked_projects(self):
		return frappe.db.get_all("Project", {'appointment': self.name}, pluck="name")


@frappe.whitelist()
def get_project(source_name, target_doc=None):
	def set_missing_values(source, target):
		customer = source.get_customer(throw=True)
		if customer:
			target.customer = customer
			target.contact_mobile = source.get('contact_mobile')
			target.contact_mobile_2 = source.get('contact_mobile_2')
			target.contact_phone = source.get('contact_phone')

		if target.applies_to_item and frappe.get_cached_value("Item", target.applies_to_item, "has_variants"):
			target.applies_to_item = None
			target.applies_to_variant_of = None

		target.run_method("set_missing_values")

	mapper = {
		"Appointment": {
			"doctype": "Project",
			"field_map": {
				"name": "appointment",
				"scheduled_dt": "appointment_dt",
				"voice_of_customer": "project_name",
				"service_advisor": "service_advisor",
				"sales_person": "sales_person",
				"description": "description",
				"applies_to_serial_no": "applies_to_serial_no",
				"opportunity": "opportunity",
				"campaign": "campaign",
				"sales_order": "sales_order",
			}
		},
		"Appointment Service Template": {
			"doctype": "Project Service Template",
			"field_map": {
				"service_template": "service_template",
				"service_template_name": "service_template_name",
				"sales_order": "sales_order",
			},
		},
		"postprocess": set_missing_values,
	}

	frappe.utils.call_hook_method("update_project_from_appointment_mapper", mapper, "Project")

	doclist = get_mapped_doc("Appointment", source_name, mapper, target_doc)

	return doclist


def update_reschedule_mapper(mapper, target_doctype):
	if not mapper.get("Appointment"):
		return

	field_map = mapper["Appointment"]["field_map"]
	field_map["sales_order"] = "sales_order"


def override_appointment_dashboard(data):
	data["transactions"].append({
		"label": _("Project"),
		"items": ["Project"]
	})

	return data
