import frappe
from frappe import _
from crm.crm.doctype.appointment.appointment import Appointment
from erpnext.overrides.lead.lead_hooks import get_customer_from_lead
from erpnext.stock.get_item_details import get_applies_to_details
from frappe.model.mapper import get_mapped_doc


class AppointmentERP(Appointment):
	force_applies_to_fields = [
		"applies_to_item", "applies_to_item_name", "applies_to_variant_of", "applies_to_variant_of_name",
		"vehicle_chassis_no", "vehicle_engine_no", "vehicle_license_plate", "vehicle_unregistered", "vehicle_color",
	]

	def onload(self):
		super().onload()

		self.set_onload('customer', self.get_customer())

		if self.meta.has_field('applies_to_vehicle'):
			from erpnext.vehicles.doctype.vehicle_log.vehicle_log import get_customer_vehicle_selector_data
			self.set_onload('customer_vehicle_selector_data', get_customer_vehicle_selector_data(
				self.get_customer(),
				self.get('applies_to_vehicle')
			))

	def validate(self):
		self.validate_duplicate_appointment()
		super().validate()

	@classmethod
	def get_allowed_party_types(cls):
		return super().get_allowed_party_types() + ["Customer"]

	def set_missing_values(self):
		super().set_missing_values()
		self.set_applies_to_details()

	def set_missing_values_after_submit(self):
		super().set_missing_values_after_submit()
		self.set_applies_to_details()

	def validate_duplicate_appointment(self):
		if not frappe.get_cached_value("Appointment Type", self.appointment_type, "validate_duplicate_appointment"):
			return

		existing_appointment = frappe.db.get_value("Appointment", {
			'scheduled_date': self.scheduled_date,
			'appointment_type': self.appointment_type,
			'applies_to_serial_no': self.applies_to_serial_no,
			'docstatus': ['=', 1],
			'name': ['!=', self.name]
		})
		if existing_appointment:
			frappe.throw(_("{0} {1} already scheduled for {2} against {3} {4}").format(
				self.appointment_type,
				frappe.get_desk_link("Appointment", existing_appointment),
				self.get_formatted("scheduled_date"),
				_("Vehicle") if self.applies_to_vehicle else _("Serial No"),
				self.applies_to_serial_no,
			))

	def validate_next_document_on_cancel(self):
		super().validate_next_document_on_cancel()
		project = self.get_linked_project()
		if project:
			frappe.throw(_("Cannot cancel appointment because it is closed by {0}").format(
				frappe.get_desk_link("Project", project)
			))

	def set_applies_to_details(self):
		if self.get("applies_to_vehicle"):
			self.applies_to_serial_no = self.applies_to_vehicle

		args = self.as_dict()
		applies_to_details = get_applies_to_details(args, for_validate=True)

		for k, v in applies_to_details.items():
			if self.meta.has_field(k) and not self.get(k) or k in self.force_applies_to_fields:
				self.set(k, v)

	def get_customer(self, throw=False):
		if self.appointment_for == "Customer":
			return self.party_name
		elif self.appointment_for == "Lead":
			return get_customer_from_lead(self.party_name, throw=throw)
		else:
			return None

	def is_appointment_closed(self):
		return super().is_appointment_closed() or self.get_linked_project()

	def get_linked_project(self):
		return frappe.db.get_value("Project", {'appointment': self.name})


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

		if source.project_template:
			target.append("project_templates", {
				"project_template": source.project_template,
				"project_template_name": source.project_template_name,
			})

		target.run_method("set_missing_values")

	doclist = get_mapped_doc("Appointment", source_name, {
		"Appointment": {
			"doctype": "Project",
			"field_map": {
				"name": "appointment",
				"scheduled_dt": "appointment_dt",
				"voice_of_customer": "project_name",
				"description": "description",
				"applies_to_vehicle": "applies_to_vehicle",
			}
		}
	}, target_doc, set_missing_values)

	return doclist


def override_appointment_dashboard(data):
	data["transactions"].append({
		"label": _("Project"),
		"items": ["Project"]
	})

	return data
