import frappe
from frappe import _
from frappe.utils import cint, cstr
import re


def validate_campaign_voucher_code(doc):
	doc.campaign_voucher_code_required = 0
	if not doc.get("campaign"):
		doc.campaign_voucher_code = None
		return

	voucher_code_required = frappe.get_cached_value("Campaign", doc.campaign, "voucher_code_required")
	doc.campaign_voucher_code_required = cint(voucher_code_required)
	if not voucher_code_required:
		doc.campaign_voucher_code = None
		return

	campaign_voucher_code = doc.get("campaign_voucher_code")
	if not campaign_voucher_code:
		frappe.throw(_("Voucher Code is required for Campaign {0}").format(frappe.bold(doc.campaign)))

	voucher_code_regex = frappe.get_cached_value("Campaign", doc.campaign, "voucher_code_regex")
	if cstr(voucher_code_regex).strip():
		if not re.match(f"^{voucher_code_regex}$", campaign_voucher_code):
			frappe.throw(_("Invalid Campaign Voucher Code {0} for Campaign {1}").format(
				frappe.bold(campaign_voucher_code),
				frappe.bold(doc.campaign),
			))

	validate_duplicate_code = frappe.get_cached_value("Campaign", doc.campaign, "validate_duplicate_voucher_code")
	if validate_duplicate_code:
		check_duplicate_campaign_voucher_code(
			campaign=doc.campaign,
			voucher_code=campaign_voucher_code,
			current_doctype=doc.doctype,
			current_docname=doc.name,
			project=doc.get("project"),
		)


def override_campaign_dashboard(data):
	data["transactions"].append({
		"label": _("Pricing Rule"),
		"items": ["Pricing Rule"]
	})

	return data


def check_duplicate_campaign_voucher_code(campaign, voucher_code, current_doctype, current_docname, project):
	if current_doctype == "Project" and current_docname:
		project = current_docname

	def validate_duplicate(doctype):
		filter_conditions = get_filters(target_doctype)

		duplicate = frappe.get_all(doctype, filters=filter_conditions, fields=["name"], limit=1)
		if duplicate:
			frappe.throw(_("{0} Campaign Voucher Code {1} has already been used in {2}").format(
				frappe.bold(campaign),
				frappe.bold(voucher_code),
				frappe.get_desk_link(doctype, duplicate[0]["name"])
			))

	def get_filters(doctype):
		filters = {
			"campaign": campaign,
			"campaign_voucher_code": voucher_code,
		}

		if doctype == "Sales Invoice":
			filters["is_return"] = 0

		if doctype == "Project":
			filters["status"] = ["!=", "Cancelled"]
		else:
			filters["docstatus"] = 1

		if doctype == current_doctype:
			filters["name"] = ["!=", current_docname]

		if project and doctype == "Project":
			filters["name"] = ["!=", project]
		elif project:
			filters["project"] = ["!=", project]

		return filters

	doctypes_to_validate = [
		"Project",
		"Sales Invoice",
	]

	if project:
		doctypes_to_validate += [
			"Sales Order",
		]

	if current_doctype not in doctypes_to_validate:
		doctypes_to_validate.append(current_doctype)

	for target_doctype in doctypes_to_validate:
		validate_duplicate(target_doctype)
