import frappe


def execute():
	frappe.db.sql("""
		update `tabSales Invoice Item` si_item
		inner join `tabItem` im on im.name = si_item.item_code
		set si_item.skip_delivery_note = 1
		where im.is_stock_item = 0 and im.is_fixed_asset = 0
	""")

	frappe.db.sql("""
		update `tabSales Invoice` si
		set si.skip_delivery_note = 1
		where not exists(
			select i.name from `tabSales Invoice Item` i where i.parent = si.name and i.skip_delivery_note = 0
		)
	""")

	frappe.db.sql("""
		update `tabSales Invoice`
		set delivery_status = 'Not Applicable'
	""")

	frappe.db.sql("""
		update `tabSales Invoice`
		set delivery_status = 'Delivered', per_delivered = 100
		where docstatus = 1 and skip_delivery_note = 0
	""")
