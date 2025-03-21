import frappe
from frappe import _
from frappe.utils import cint


def validate_campaign_voucher_code(doc):
	voucher_code_required = False
	if doc.get("campaign"):
		voucher_code_required = frappe.get_cached_value("Campaign", doc.campaign, "voucher_code_required")

	doc.campaign_voucher_code_required = cint(voucher_code_required)

	if voucher_code_required:
		if not doc.get("campaign_voucher_code"):
			frappe.throw(_("Voucher Code is required for Campaign {0}").format(
				frappe.bold(doc.campaign)
			))
	else:
		doc.campaign_voucher_code = None


def override_campaign_dashboard(data):
	data["transactions"].append({
		"label": _("Pricing Rule"),
		"items": ["Pricing Rule"]
	})

	return data
