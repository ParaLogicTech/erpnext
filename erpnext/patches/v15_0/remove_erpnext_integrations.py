import frappe

DOCTYPES = (
	"Amazon MWS Settings",
	"Exotel Settings",
	"GoCardless Mandate",
	"GoCardless Settings",
	"Plaid Settings",
	"QuickBooks Migrator",
	"Shopify Log",
	"Shopify Settings",
	"Shopify Tax Account",
	"Shopify Webhook Detail",
	"Tally Migration",
	"Woocommerce Settings",
)

# The payments app ships its own copies of these. Depending on install order, a site may have them
# registered under erpnext's module, so give them back to payments instead of deleting them.
PAYMENTS_DOCTYPES = ("GoCardless Mandate", "GoCardless Settings")


def execute():
	payments_installed = "payments" in frappe.get_installed_apps()

	to_delete = []
	for dt in DOCTYPES:
		module = frappe.db.get_value("DocType", dt, "module")

		if dt in PAYMENTS_DOCTYPES and payments_installed:
			if module != "Payment Gateways":
				frappe.reload_doc("payment_gateways", "doctype", frappe.scrub(dt), force=True)
			continue

		# A missing DocType record was already removed as an orphan by an earlier migrate,
		# which leaves its table and Singles values behind.
		if not module or module == "ERPNext Integrations":
			to_delete.append(dt)

	if to_delete:
		frappe.db.delete("Custom Field", {"dt": ("in", to_delete)})
		frappe.db.delete("Property Setter", {"doc_type": ("in", to_delete)})
		frappe.db.delete("Workspace Link", {"link_to": ("in", to_delete)})
		frappe.db.delete("Workspace Shortcut", {"link_to": ("in", to_delete)})

	frappe.delete_doc_if_exists("Workspace", "ERPNext Integrations")

	for dt in to_delete:
		frappe.delete_doc(
			"DocType", dt, force=True, ignore_permissions=True, ignore_missing=True,
			delete_permanently=True,
		)
		frappe.db.delete("Singles", {"doctype": dt})
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{dt}`")
