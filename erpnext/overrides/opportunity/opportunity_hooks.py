import frappe
from frappe import _
from frappe.utils import cint
from crm.crm.doctype.opportunity.opportunity import Opportunity
from frappe.model.mapper import get_mapped_doc
from erpnext.utilities.transaction_base import validate_uom_is_integer, validate_uom_is_convertible
from erpnext.stock.get_item_details import get_applies_to_details, get_force_applies_to_fields
from erpnext.overrides.lead.lead_hooks import get_customer_from_lead
from erpnext.projects.doctype.service_template.service_template import add_service_template_items


class OpportunityERP(Opportunity):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		self.force_item_fields = ["item_group", "brand"]
		self.force_applies_to_fields = get_force_applies_to_fields(self.doctype)

	def onload(self):
		if self.opportunity_from == "Customer":
			self.set_onload('customer', self.party_name)
		elif self.opportunity_from == "Lead":
			self.set_onload('customer', get_customer_from_lead(self.party_name))

	def validate(self):
		super().validate()
		validate_uom_is_convertible(self)
		validate_uom_is_integer(self, "uom", "qty")
		self.validate_maintenance_schedule()

	@classmethod
	def get_allowed_party_types(cls):
		return super().get_allowed_party_types() + ["Customer"]

	def set_missing_values(self):
		super().set_missing_values()
		self.set_item_details()
		self.set_applies_to_details()

	def validate_maintenance_schedule(self):
		if not self.get("maintenance_schedule"):
			return

		filters = {
			'maintenance_schedule': self.maintenance_schedule,
			'maintenance_schedule_row': self.maintenance_schedule_row
		}
		if not self.is_new():
			filters['name'] = ['!=', self.name]

		dup = frappe.get_value("Opportunity", filters=filters)
		if dup:
			frappe.throw(_("{0} already exists for this scheduled maintenance".format(frappe.get_desk_link("Opportunity", dup))))

	def set_item_details(self):
		for d in self.items:
			if not d.item_code:
				continue

			item_details = get_item_details(d.item_code)
			for k, v in item_details.items():
				if d.meta.has_field(k) and (not d.get(k) or k in self.force_item_fields):
					d.set(k, v)

	def set_applies_to_details(self):
		args = self.as_dict()
		applies_to_details = get_applies_to_details(args, for_validate=True)

		for k, v in applies_to_details.items():
			if self.meta.has_field(k) and not self.get(k) or k in self.force_applies_to_fields:
				self.set(k, v)

	def is_converted(self):
		if self.is_new():
			return super().is_converted()

		if self.has_ordered_quotation():
			return True

		return super().is_converted()

	def has_active_quotation(self):
		quotations = get_active_quotations(self.name)
		if quotations:
			return True

		return super().has_active_quotation()

	def has_lost_quotation(self):
		lost_quotations = self.get_lost_quotations()
		if lost_quotations:
			return True

		return super().has_lost_quotation()

	def has_ordered_quotation(self):
		if self.is_new():
			return None

		quotation = frappe.db.get_value("Quotation", {
			"opportunity": self.name,
			"docstatus": 1,
			"status": "Ordered",
		})

		return quotation

	def get_lost_quotations(self):
		if self.is_new():
			return []

		lost_quotations = frappe.get_all("Quotation", {
			"opportunity": self.name,
			"docstatus": 1,
			"status": 'Lost'
		})

		return [d.name for d in lost_quotations]

	def set_next_document_is_lost(self, is_lost, lost_reasons_list=None, detailed_reason=None):
		super().set_next_document_is_lost(is_lost, lost_reasons_list, detailed_reason)

		quotations = get_active_quotations(self.name) if is_lost else self.get_lost_quotations()
		for name in quotations:
			doc = frappe.get_doc("Quotation", name)
			doc.flags.from_opportunity = True
			doc.set_is_lost(is_lost, lost_reasons_list, detailed_reason)


def get_active_quotations(opportunity):
	if not opportunity:
		return []

	quotations = frappe.get_all('Quotation', {
		'opportunity': opportunity,
		'status': ("not in", ['Lost', 'Closed']),
		'docstatus': 1
	}, 'name')

	return [d.name for d in quotations]


@frappe.whitelist()
def get_item_details(item_code):
	item_details = frappe.get_cached_doc("Item", item_code) if item_code else frappe._dict()

	return {
		'item_name': item_details.item_name,
		'description': item_details.description,
		'uom': item_details.stock_uom,
		'image': item_details.image,
		'item_group': item_details.item_group,
		'brand': item_details.brand,
	}


@frappe.whitelist()
def create_quotation(
	opportunity,
	data=None,
	map_items=True,
	map_service_templates=True,
	service_templates=None,
):
	data = frappe.parse_json(data) if data else frappe._dict()

	target_doc = frappe.new_doc("Quotation")
	for key, value in data.items():
		if target_doc.meta.has_field(key):
			target_doc.set(key, value)

	target_doc = make_quotation(
		opportunity,
		target_doc=target_doc,
		map_items=map_items,
		map_service_templates=map_service_templates,
		service_templates=service_templates,
	)

	target_doc.insert()
	return target_doc


@frappe.whitelist()
def make_quotation(
	source_name,
	target_doc=None,
	map_items=True,
	map_service_templates=True,
	service_templates=None,
):
	from erpnext.overrides.lead.lead_hooks import add_sales_person_from_source

	map_items = cint(map_items)
	map_service_templates = cint(map_service_templates)
	service_templates = frappe.parse_json(service_templates) if service_templates else []

	def set_missing_values(source, target):
		add_sales_person_from_source(source, target)

		bill_to = target.bill_to
		if not bill_to and target.quotation_to == "Customer":
			bill_to = target.party_name

		if map_service_templates:
			for st_row in source.get("service_templates"):
				if st_row.service_template:
					target = add_service_template_items(
						target,
						st_row.service_template,
						applies_to_item=target.applies_to_item,
						applies_to_customer=bill_to,
						check_duplicate=False,
						postprocess=False,
					)

		if service_templates:
			for service_template in service_templates:
				target = add_service_template_items(
					target,
					service_template,
					applies_to_item=target.applies_to_item,
					applies_to_customer=bill_to,
					check_duplicate=False,
					postprocess=False,
				)

		target.run_method("postprocess_after_mapping")

	mapper = {
		"Opportunity": {
			"doctype": "Quotation",
			"field_map": {
				"opportunity_from": "quotation_to",
				"party_name": "party_name",
				"name": "opportunity",
				"applies_to_serial_no": "applies_to_serial_no",
			}
		},
	}

	if map_items:
		mapper["Opportunity Item"] = {
			"doctype": "Quotation Item",
			"field_map": {
				"uom": "stock_uom",
			},
			"add_if_empty": True
		}

	doclist = get_mapped_doc("Opportunity", source_name, mapper, target_doc, set_missing_values)

	return doclist


@frappe.whitelist()
def make_request_for_quotation(source_name, target_doc=None):
	doclist = get_mapped_doc("Opportunity", source_name, {
		"Opportunity": {
			"doctype": "Request for Quotation"
		},
		"Opportunity Item": {
			"doctype": "Request for Quotation Item",
			"field_map": [
				["name", "opportunity_item"],
				["parent", "opportunity"],
				["uom", "uom"]
			]
		}
	}, target_doc)

	return doclist


def get_customer_from_opportunity(source):
	if source and source.get('party_name'):
		if source.get('opportunity_from') == 'Lead':
			customer = get_customer_from_lead(source.get('party_name'), throw=True)
			return frappe.get_cached_doc('Customer', customer)

		elif source.get('opportunity_from') == 'Customer':
			return frappe.get_cached_doc('Customer', source.get('party_name'))


@frappe.whitelist()
def make_supplier_quotation(source_name, target_doc=None):
	doclist = get_mapped_doc("Opportunity", source_name, {
		"Opportunity": {
			"doctype": "Supplier Quotation",
			"field_map": {
				"name": "opportunity"
			}
		},
		"Opportunity Item": {
			"doctype": "Supplier Quotation Item",
			"field_map": {
				"uom": "stock_uom"
			}
		}
	}, target_doc)

	return doclist


def update_appointment_mapper(mapper, target_doctype):
	mapper["Opportunity Service Template"] = {
		"doctype": "Appointment Service Template",
		"field_map": {
			"service_template": "service_template",
			"service_template_name": "service_template_name",
		},
	}


def override_opportunity_dashboard(data):
	data["transactions"].insert(0, {
		"label": _("Quotation"),
		"items": ["Quotation", "Supplier Quotation"]
	})

	project_items = ["Project"]

	appointment_section = [d for d in data["transactions"] if d["label"] == _("Appointment")]
	if appointment_section:
		appointment_section = appointment_section[0]
		appointment_section["items"] += project_items
	else:
		data["transactions"].append({
			"label": _("Appointment"),
			"items": project_items,
		})

	return data
