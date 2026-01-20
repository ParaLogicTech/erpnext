import frappe


def execute():
	if not frappe.db.exists("DocType", "Account Group"):
		return
	if not frappe.db.has_column("Account Group", "is_root_level"):
		return

	asset_groups = frappe.get_all("Account Group", fields=["name", "is_root_level", "is_fixed_asset_root"])

	frappe.reload_doc("accounts", "doctype", "account_group")

	frappe.db.sql("""
		update `tabAccount Group`
		set group_level = 'Sub Group'
	""")

	for ag in asset_groups:
		if ag.is_root_level:
			frappe.db.set_value("Account Group", ag.name, "group_level", "Report Root", update_modified=False)

		if ag.is_fixed_asset_root:
			frappe.db.set_value("Account Group", ag.name, "group_level", "Fixed Asset Root", update_modified=False)

			group_doc = frappe.get_doc("Account Group", ag.name)
			for row in group_doc.rows:
				if row.row_type == "Account Group":
					frappe.db.set_value("Account Group", row.account_group, "group_level", "Fixed Asset Category", update_modified=False)
