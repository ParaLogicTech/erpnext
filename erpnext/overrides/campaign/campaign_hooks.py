import frappe
from frappe import _
from frappe.utils import cint
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

	if not voucher_code_regex:
		return

	if not re.match(f"^{voucher_code_regex}$", campaign_voucher_code):
		frappe.throw(_("Invalid Voucher Code {0}. Please enter a code that matches the required format.").format(frappe.bold(campaign_voucher_code)))


def override_campaign_dashboard(data):
	data["transactions"].append({
		"label": _("Pricing Rule"),
		"items": ["Pricing Rule"]
	})

	return data
