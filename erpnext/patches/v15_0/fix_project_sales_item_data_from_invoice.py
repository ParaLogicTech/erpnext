import frappe


def execute():
	projects = frappe.db.sql_list("""
		select name
		from `tabProject`
		where billing_status = 'Fully Billed'
			and total_billable_amount != total_billed_amount
		order by project_date desc
	""")

	for i, name in enumerate(projects):
		print(f"{i+1}/{len(projects)}: {name}")

		doc = frappe.get_doc("Project", name)
		doc.set_billing_and_delivery_status(update=True, update_modified=False)
		doc.set_costing(update=True, update_modified=False)
		doc.clear_cache()
