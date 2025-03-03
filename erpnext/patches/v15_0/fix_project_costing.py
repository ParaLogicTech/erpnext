import frappe


def execute():
	projects = frappe.db.sql_list("""
		select p.name
		from `tabProject` p
		where exists(select ste.name from `tabStock Entry` ste where ste.project = p.name and ste.docstatus = 1)
			or exists(select prec.name from `tabPurchase Receipt Item` prec where prec.project = p.name and prec.docstatus = 1)
			or exists(select pinv.name from `tabPurchase Invoice Item` pinv where pinv.project = p.name and pinv.docstatus = 1)
			or exists(select dn.name from `tabDelivery Note` dn where dn.project = p.name and dn.docstatus = 1)
	""")

	for i, name in enumerate(projects):
		print(f"{i+1}/{len(projects)}: {name}")
		doc = frappe.get_doc("Project", name)
		doc.set_purchase_values(update=True, update_modified=False)
		doc.set_material_consumed_cost(update=True, update_modified=False)
		doc.set_material_cost_of_sales(update=True, update_modified=False)
		doc.set_gross_margin(update=True, update_modified=False)
		doc.clear_cache()
