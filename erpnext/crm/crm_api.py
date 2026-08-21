import frappe
from frappe import _
from frappe.utils import cstr
from frappe.regional.regional import get_all_mobile_formats
from frappe.desk.reportview import get_match_cond


@frappe.whitelist()
def find_customer_or_lead(
	customer_id=None,
	email_id=None,
	mobile_no=None,
	national_id=None,
	customer_type=None,
):
	return get_customer_or_lead(
		customer_id=customer_id,
		email_id=email_id,
		mobile_no=mobile_no,
		national_id=national_id,
		customer_type=customer_type,
	)


def get_customer_or_lead(
	customer_id=None,
	email_id=None,
	mobile_no=None,
	national_id=None,
	customer_type=None,
	ignore_permissions=False,
):
	if (
		not ignore_permissions
		and not frappe.has_permission("Customer", "read")
		and not frappe.has_permission("Lead", "read")
	):
		frappe.throw(_("Not Permitted"), frappe.PermissionError)

	mobile_nos = get_all_mobile_formats(mobile_no)
	email_id = cstr(email_id).strip()
	national_id = cstr(national_id).strip()

	customer = None
	if ignore_permissions or frappe.has_permission("Customer", "read"):
		customer = search_customer(
			customer_id=customer_id,
			email_id=email_id,
			mobile_nos=mobile_nos,
			national_id=national_id,
			customer_type=customer_type,
			ignore_permissions=ignore_permissions,
		)
	if customer:
		return frappe._dict({
			"party_type": "Customer",
			"party": customer.name,
			"party_name": customer.customer_name,
			"customer_type": customer.customer_type,
			"email_id": customer.email_id,
			"mobile_no": customer.mobile_no,
			"disabled": customer.disabled,
			"creation": customer.creation,
		})

	lead = None
	if ignore_permissions or frappe.has_permission("Lead", "read"):
		lead = search_lead(
			email_id=email_id,
			mobile_nos=mobile_nos,
			national_id=national_id,
			ignore_permissions=ignore_permissions,
		)
	if lead:
		return frappe._dict({
			"party_type": "Lead",
			"party": lead.name,
			"party_name": lead.lead_name or lead.company_name,
			"customer_type": "Company" if lead.company_name else "Individual",
			"email_id": lead.email_id,
			"mobile_no": lead.mobile_no,
			"disabled": 0,
			"creation": lead.creation,
		})

	return None


def search_customer(
	customer_id=None,
	email_id=None,
	mobile_nos=None,
	national_id=None,
	customer_type=None,
	ignore_permissions=False,
):
	def sorter(data):
		no_of_matches = 0
		if email_id and data.email_id == email_id:
			no_of_matches += 1
		if mobile_nos and data.mobile_no in mobile_nos:
			no_of_matches += 1
		if national_id and data.tax_cnic == national_id:
			no_of_matches += 1

		return (
			1 if customer_id and data.name == customer_id else 0,
			0 if data.disabled else 1,
			no_of_matches,
			1 if data.customer_type == "Individual" else 0,
			-data.creation.timestamp()
		)

	if mobile_nos and isinstance(mobile_nos, str):
		mobile_nos = [mobile_nos]

	or_conditions = []
	if customer_id:
		or_conditions.append("name = %(customer_id)s")
	if email_id:
		or_conditions.append("email_id = %(email_id)s")
	if mobile_nos:
		or_conditions.append("mobile_no in %(mobile_nos)s")
	if national_id:
		or_conditions.append("tax_cnic = %(national_id)s")

	if not or_conditions:
		return None

	or_conditions_str = " or ".join(or_conditions)

	customer_type_condition = ""
	if customer_type:
		customer_type_condition = f"and customer_type = %(customer_type)s"

	mcond = ""
	if not ignore_permissions:
		mcond = get_match_cond("Customer")

	customers = frappe.db.sql(f"""
		select name, customer_name, email_id, mobile_no, tax_cnic, customer_type, disabled, creation
		from `tabCustomer`
		where ({or_conditions_str}) {customer_type_condition} {mcond}
	""", {
		"customer_id": customer_id,
		"email_id": email_id,
		"mobile_nos": mobile_nos,
		"national_id": national_id,
		"customer_type": customer_type,
	}, as_dict=1)

	customers = sorted(customers, key=sorter, reverse=True)
	return customers[0] if customers else None


def search_lead(
	email_id=None,
	mobile_nos=None,
	national_id=None,
	ignore_permissions=False,
):
	def sorter(data):
		no_of_matches = 0
		if email_id and data.email_id == email_id:
			no_of_matches += 1
		if mobile_nos and data.mobile_no in mobile_nos:
			no_of_matches += 1
		if national_id and data.tax_cnic == national_id:
			no_of_matches += 1

		if data.status == "Converted":
			status_priority = 4
		elif data.status == "Opportunity":
			status_priority = 3
		elif data.status == "Interested":
			status_priority = 2
		elif data.status == "Open":
			status_priority = 0
		else:
			status_priority = 1

		return (
			status_priority,
			no_of_matches,
			-data.creation.timestamp()
		)

	if mobile_nos and isinstance(mobile_nos, str):
		mobile_nos = [mobile_nos]

	or_conditions = []
	if email_id:
		or_conditions.append("email_id = %(email_id)s")
	if mobile_nos:
		or_conditions.append("mobile_no in %(mobile_nos)s")
	if national_id:
		or_conditions.append("tax_cnic = %(national_id)s")

	if not or_conditions:
		return None

	or_conditions_str = " or ".join(or_conditions)

	mcond = ""
	if not ignore_permissions:
		mcond = get_match_cond("Lead")

	leads = frappe.db.sql(f"""
		select name, lead_name, organization_lead, company_name, email_id, mobile_no, tax_cnic, status, creation
		from `tabLead`
		where {or_conditions_str} {mcond}
	""", {
		"email_id": email_id,
		"mobile_nos": mobile_nos,
		"national_id": national_id,
	}, as_dict=1)

	leads = sorted(leads, key=sorter, reverse=True)
	return leads[0] if leads else None
