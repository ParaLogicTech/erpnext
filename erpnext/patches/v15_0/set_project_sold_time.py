import frappe


def execute():
	projects = frappe.db.sql_list("""
		select distinct p.project
		from `tabSales Order Item` i
		inner join `tabSales Order` p on p.name = i.parent
		where p.docstatus = 1 and p.project != '' and p.project is not null and exists(
			select cf.name
			from `tabUOM Conversion Detail` cf
			where cf.parent = i.item_code and cf.parenttype = 'Item' and cf.uom = 'Hour'
		)
	""")

	projects += frappe.db.sql_list("""
		select distinct i.project
		from `tabSales Invoice Item` i
		inner join `tabSales Invoice` p on p.name = i.parent
		where p.docstatus = 1 and i.project != '' and i.project is not null and exists(
			select cf.name
			from `tabUOM Conversion Detail` cf
			where cf.parent = i.item_code and cf.parenttype = 'Item' and cf.uom = 'Hour'
		)
	""")

	projects = list(set(projects))
	if projects:
		print("Setting Sold Time")
		for i, name in enumerate(projects):
			print(f"{i+1}/{len(projects)}: {name}")
			doc = frappe.get_doc("Project", name)
			doc.set_sales_amount()
			doc.db_set("sold_time", doc.sold_time, update_modified=False)
			doc.clear_cache()
