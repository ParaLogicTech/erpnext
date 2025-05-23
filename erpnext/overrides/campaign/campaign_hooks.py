import frappe
from frappe import _
from frappe.utils import cint, cstr
from frappe.utils import get_link_to_form
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
	if not validate_duplicate_code:
		return

	project = getattr(doc, "project", None)

	check_duplicate_voucher_across_transactions(
		campaign=doc.campaign,
		voucher_code=campaign_voucher_code,
		current_doctype=doc.doctype,
		current_doc_name=doc.name,
		project=project,
	)


def override_campaign_dashboard(data):
	data["transactions"].append({
		"label": _("Pricing Rule"),
		"items": ["Pricing Rule"]
	})

	return data

def check_duplicate_voucher_across_transactions(campaign, voucher_code, current_doctype, current_doc_name, project):
	standard_filters = {
		"campaign": campaign,
		"campaign_voucher_code": voucher_code,
	}

	def get_common_filters(doctype, exclude_repair_order=False):
		additional_filters = standard_filters.copy()

		if doctype == current_doctype:
			additional_filters["name"] = ["!=", current_doc_name]

		if doctype == "Sales Invoice":
			additional_filters["is_return"] = 0

		if doctype == "Project":
			additional_filters["docstatus"] = ["!=", 2]
		else:
			additional_filters["docstatus"] = 1

		if exclude_repair_order and project:
			additional_filters["project"] = ["!=", project]
		elif project and not exclude_repair_order:
			additional_filters["name"] = ["!=", project]

		return additional_filters

	def validate_duplicate(doctype, filter_conditions):
		duplicate = frappe.get_all(doctype, filters=filter_conditions, fields=["name"], limit=1)
		if duplicate:
			link = frappe.bold(get_link_to_form(doctype, duplicate[0]["name"]))
			frappe.throw(_("Duplicate voucher found in submitted transaction:\n\n{0}: {1}").format(doctype, link))

	doctype_validation_rules = [
		("Project", False),
		("Sales Order", True),
		("Sales Invoice", True)
	]

	for target_doctype, exclude_repair in doctype_validation_rules:
		filters = get_common_filters(target_doctype, exclude_repair_order=exclude_repair)
		validate_duplicate(target_doctype, filters)
