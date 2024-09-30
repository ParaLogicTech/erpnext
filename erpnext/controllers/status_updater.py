# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import flt, comma_or
from frappe.utils.status_updater import StatusUpdater
from frappe import _


def validate_status(status, options):
	if status not in options:
		frappe.throw(_("Status must be one of {0}").format(comma_or(options)))


class StatusUpdaterERP(StatusUpdater):
	def get_under_delivery_percentage(self):
		return flt(frappe.get_cached_value("Stock Settings", None, "under_delivery_allowance"))

	def get_allowance_for(self, allowance_type, item_code=None):
		"""
			Returns the allowance for the item, if not set, returns global allowance
		"""

		if not allowance_type:
			return 0

		allowance = 0
		if allowance_type == "billing":
			allowance_field = "over_billing_allowance"
		elif allowance_type == "production":
			allowance_field = "over_production_allowance"
		else:
			allowance_field = "over_delivery_receipt_allowance"

		if item_code:
			allowance = flt(frappe.get_cached_value('Item', item_code, allowance_field))

		if not allowance:
			if allowance_type == "billing":
				allowance = flt(frappe.get_cached_value('Accounts Settings', None, 'over_billing_allowance'))
			elif allowance_type == "production":
				allowance = flt(frappe.get_cached_value('Manufacturing Settings', None, 'overproduction_percentage_for_work_order'))
			else:
				allowance = flt(frappe.get_cached_value('Stock Settings', None, 'over_delivery_receipt_allowance'))

		return allowance

	def get_overallowance_error_suggestion_message(self, allowance_type):
		if not allowance_type:
			return ""
		elif allowance_type == "billing":
			return _('To allow Over Billing, update "Over Billing Allowance" in Accounts Settings or the Item.')
		else:
			return _('To allow Over Receipt/Delivery, update "Over Receipt/Delivery Allowance" in Stock Settings or the Item.')
