import frappe


def execute():
	frappe.db.sql("""
		update `tabCustomer Feedback` fb
		inner join `tabProject` p on p.name = fb.project
		set
			fb.contact_person = p.contact_person,
			fb.contact_display = p.contact_display,
			fb.contact_mobile = p.contact_mobile,
			fb.contact_phone = p.contact_phone,
			fb.contact_email = p.contact_email
		where fb.feedback_from = 'Customer' and fb.party_name = p.customer
	""")
