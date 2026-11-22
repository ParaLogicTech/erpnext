import frappe

MODULES = ("Non Profit", "Agriculture", "Hotels", "Restaurant", "Education", "Healthcare")
DOMAINS = ("Non Profit", "Agriculture", "Hospitality", "Education", "Healthcare")

# Custom Fields that the removed domains added to core DocTypes (see the old erpnext/domains/*.py)
DOMAIN_CUSTOM_FIELDS = {
	"Sales Invoice": ("patient", "patient_name", "ref_practitioner", "restaurant", "restaurant_table"),
	"Price List": ("restaurant_menu",),
}


def execute():
	doctypes = frappe.get_all("DocType", filters={"module": ("in", MODULES)}, pluck="name")
	roles = frappe.get_all("Role", filters={"restrict_to_domain": ("in", DOMAINS)}, pluck="name")

	deactivate_domains()
	delete_customizations(doctypes)
	delete_dependent_records(doctypes)
	delete_roles(roles)
	delete_doctypes(doctypes)

	for party_type in ("Student", "Member", "Donor"):
		frappe.db.delete("Party Type", {"name": party_type})

	# rows on Users / Module Profiles blocking the removed modules
	frappe.db.delete("Block Module", {"module": ("in", MODULES)})

	frappe.db.delete("Domain", {"name": ("in", DOMAINS)})
	frappe.db.delete("Module Def", {"name": ("in", MODULES)})

	frappe.clear_cache()


def deactivate_domains():
	frappe.db.delete("Has Domain", {"parent": "Domain Settings", "domain": ("in", DOMAINS)})
	frappe.cache.delete_value("active_domains")


def delete_customizations(doctypes):
	if doctypes:
		frappe.db.delete("Custom Field", {"dt": ("in", doctypes)})
		frappe.db.delete("Custom Field", {
			"fieldtype": ("in", ("Link", "Table", "Table MultiSelect")),
			"options": ("in", doctypes),
		})
		frappe.db.delete("Property Setter", {"doc_type": ("in", doctypes)})
		frappe.db.delete("Custom DocPerm", {"parent": ("in", doctypes)})
		frappe.db.delete("Client Script", {"dt": ("in", doctypes)})
		frappe.db.delete("User Permission", {"allow": ("in", doctypes)})
		frappe.db.delete("DocShare", {"share_doctype": ("in", doctypes)})

	for dt, fieldnames in DOMAIN_CUSTOM_FIELDS.items():
		frappe.db.delete("Custom Field", {"dt": dt, "fieldname": ("in", fieldnames)})


def delete_dependent_records(doctypes):
	by_module = {
		"Report": "module",
		"Print Format": "module",
		"Page": "module",
		"Workspace": "module",
		"Dashboard Chart": "module",
		"Number Card": "module",
		"Notification": "module",
		"Web Form": "module",
		"Module Onboarding": "module",
	}
	by_doctype = {
		"Report": "ref_doctype",
		"Print Format": "doc_type",
		"Dashboard Chart": "document_type",
		"Number Card": "document_type",
		"Notification": "document_type",
		"Web Form": "doc_type",
		"Server Script": "reference_doctype",
		"Kanban Board": "reference_doctype",
		"Onboarding Step": "reference_document",
	}

	to_delete = set()
	for record_doctype, field in by_module.items():
		if frappe.db.has_column(record_doctype, field):
			for name in frappe.get_all(record_doctype, filters={field: ("in", MODULES)}, pluck="name"):
				to_delete.add((record_doctype, name))

	if doctypes:
		for record_doctype, field in by_doctype.items():
			if frappe.db.has_column(record_doctype, field):
				for name in frappe.get_all(record_doctype, filters={field: ("in", doctypes)}, pluck="name"):
					to_delete.add((record_doctype, name))

		# links and shortcuts to the removed DocTypes inside workspaces that stay
		frappe.db.delete("Workspace Link", {"link_to": ("in", doctypes)})
		frappe.db.delete("Workspace Shortcut", {"link_to": ("in", doctypes)})

	for record_doctype, name in sorted(to_delete):
		frappe.delete_doc(
			record_doctype, name, force=True, ignore_permissions=True, ignore_missing=True,
			delete_permanently=True,
		)


def delete_roles(roles):
	if not roles:
		return

	frappe.db.delete("Has Role", {"role": ("in", roles)})
	frappe.db.delete("DocPerm", {"role": ("in", roles)})
	frappe.db.delete("Custom DocPerm", {"role": ("in", roles)})
	frappe.db.delete("Role", {"name": ("in", roles)})


def delete_doctypes(doctypes):
	for dt in doctypes:
		is_single = frappe.db.get_value("DocType", dt, "issingle")
		frappe.delete_doc(
			"DocType", dt, force=True, ignore_permissions=True, ignore_missing=True,
			delete_permanently=True,
		)
		if is_single:
			frappe.db.delete("Singles", {"doctype": dt})
		else:
			frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{dt}`")
