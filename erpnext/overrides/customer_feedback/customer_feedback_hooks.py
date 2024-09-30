import frappe
from crm.crm.doctype.customer_feedback.customer_feedback import CustomerFeedback


class CustomerFeedbackERP(CustomerFeedback):
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

			if 'Vehicles' in frappe.get_active_domains() and self.applies_to_vehicle:
				communication_doc.append("timeline_links", {
					"link_doctype": "Vehicle",
					"link_name": self.applies_to_vehicle,
				})

		return communication_doc
