import frappe


def execute():
	# Old v10 "user progress" onboarding; Frappe no longer calls it.
	# The DocType record may already be gone as an orphan, so clean up the data either way.
	for dt in ("Setup Progress", "Setup Progress Action"):
		frappe.delete_doc(
			"DocType", dt, force=True, ignore_permissions=True, ignore_missing=True,
			delete_permanently=True,
		)
		frappe.db.delete("Singles", {"doctype": dt})
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{dt}`")
