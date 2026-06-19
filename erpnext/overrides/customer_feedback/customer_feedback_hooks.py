import frappe
from crm.crm.doctype.customer_feedback.customer_feedback import CustomerFeedback
from erpnext.accounts.party import _get_contact_details
from erpnext.stock.get_item_details import get_applies_to_details, get_force_applies_to_fields


class CustomerFeedbackERP(CustomerFeedback):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.force_applies_to_fields = get_force_applies_to_fields(self.doctype)

	def validate(self):
		self.set_reference_from_project()
		super().validate()
		self.set_branch()

	def set_reference_from_project(self):
		if self.project and not self.reference_name:
			self.reference_doctype = "Project"
			self.reference_name = self.project

		if self.reference_doctype == "Project" and self.reference_name and not self.project:
			self.project = self.reference_name
	
	def set_branch(self):
		if not self.branch:
			if self.project:
				self.branch = frappe.get_cached_value("Project", self.project, "branch")
			elif (
				self.reference_doctype
				and self.reference_name
				and frappe.get_meta(self.reference_doctype).has_field("branch")
			):
				self.branch = frappe.get_cached_value(
					self.reference_doctype,
					self.reference_name,
					"branch",
				)

	def set_missing_values(self):
		super().set_missing_values()
		self.set_applies_to_details()

	def set_applies_to_details(self):
		args = self.as_dict()
		if self.reference_doctype == "Project" and self.reference_name:
			args.project = self.reference_name

		applies_to_details = get_applies_to_details(args, for_validate=True)

		for k, v in applies_to_details.items():
			if self.meta.has_field(k) and not self.get(k) or k in self.force_applies_to_fields:
				self.set(k, v)

	@classmethod
	def get_allowed_party_types(cls):
		return super().get_allowed_party_types() + ["Customer"]

	def make_communication_doc(self, for_field, set_timeline_links):
		communication_doc = super().make_communication_doc(for_field, set_timeline_links)

		if set_timeline_links:
			if self.get("applies_to_serial_no"):
				communication_doc.append("timeline_links", {
					"link_doctype": "Serial No",
					"link_name": self.applies_to_serial_no,
				})

		return communication_doc


def get_customer_feedback_contact_details_hook(args, out):
	if not args.project:
		return

	party = frappe.get_cached_doc(args.feedback_from, args.party_name)
	lead = party if party.doctype == "Lead" else None

	if not args.contact_person and party.doctype == "Customer":
		project_details = frappe.db.get_value("Project", args.project, ["customer", "contact_person"], as_dict=True)
		if party.name == project_details.customer:
			out.contact_person = project_details.contact_person

	out.update(_get_contact_details(out.contact_person, lead=lead, project=args.project))
