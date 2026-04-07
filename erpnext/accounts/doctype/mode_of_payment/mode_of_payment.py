# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import cint
from frappe.model.document import Document


class ModeofPayment(Document):
	def on_update(self):
		frappe.cache.delete_key("bootinfo")

	def validate(self):
		self.validate_accounts()
		self.validate_repeating_companies()
		self.validate_pos_mode_of_payment()

	def validate_repeating_companies(self):
		"""Error when Same Company is entered multiple times in accounts"""
		accounts_list = []
		for entry in self.accounts:
			accounts_list.append(entry.company)

		if len(accounts_list) != len(set(accounts_list)):
			frappe.throw(_("Same Company is entered more than once"))

	def validate_accounts(self):
		for entry in self.accounts:
			"""Error when Company of Ledger account doesn't match with Company Selected"""
			if frappe.db.get_value("Account", entry.default_account, "company") != entry.company:
				frappe.throw(_("Account {0} does not match with Company {1} in Mode of Account: {2}")
					.format(entry.default_account, entry.company, self.name))

	def validate_pos_mode_of_payment(self):
		if not self.enabled:
			pos_profiles = frappe.db.sql("""SELECT sip.parent FROM `tabSales Invoice Payment` sip 
				WHERE sip.parenttype = 'POS Profile' and sip.mode_of_payment = %s""", (self.name))
			pos_profiles = list(map(lambda x: x[0], pos_profiles))
			
			if pos_profiles:
				message = "POS Profile " + frappe.bold(", ".join(pos_profiles)) + " contains \
					Mode of Payment " + frappe.bold(str(self.name)) + ". Please remove them to disable this mode."
				frappe.throw(_(message), title="Not Allowed")


@frappe.whitelist()
def get_mode_of_payment_account(
	mode_of_payment,
	company,
	pos_profile=None,
	override_till_account=True,
	direction="incoming",
):
	account = None

	if pos_profile:
		pos_profile = frappe.get_cached_doc("POS Profile", pos_profile)
		if pos_profile.till_account and cint(override_till_account):
			account = pos_profile.till_account
		elif mode_of_payment:
			pos_mode_row = [d for d in pos_profile.payments if d.mode_of_payment == mode_of_payment]
			pos_mode_row = pos_mode_row[0] if pos_mode_row else None
			if pos_mode_row:
				account = pos_mode_row.account

	if not account and mode_of_payment:
		mop_doc = frappe.get_cached_doc("Mode of Payment", mode_of_payment)
		account_row = [d for d in mop_doc.accounts if d.company == company]
		account_row = account_row[0] if account_row else None
		if account_row:
			account = account_row.default_outgoing_account if direction == "outgoing" else account_row.default_account

	return account
