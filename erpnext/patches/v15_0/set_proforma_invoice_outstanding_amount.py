import frappe
from erpnext.accounts.party import get_party_account


def execute():
	names = frappe.get_all("Proforma Invoice", {"docstatus": ["<", 2]}, pluck="name")
	for name in names:
		doc = frappe.get_doc("Proforma Invoice", name)

		if not doc.debit_to:
			billing_party_type, billing_party, billing_party_name = doc.get_billing_party()
			account = get_party_account(billing_party_type, billing_party, doc.company, transaction_type=doc.transaction_type)
			doc.db_set("debit_to", account, update_modified=False)
		if not doc.party_account_currency:
			currency = frappe.db.get_value("Account", doc.debit_to, "account_currency", cache=1)
			doc.db_set("party_account_currency", currency, update_modified=False)

		doc.set_outstanding_amount(update=True, update_modified=False)
		doc.clear_cache()
