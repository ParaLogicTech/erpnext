import frappe


def execute():
	frappe.db.sql("""
		update `tabPacking Slip` ps
		set ps.is_reassigned = 0
		where ps.can_reassign = 1 and ps.customer = ps.original_customer and not exists(select i.name from `tabPacking Slip Item` i
			where i.parent = ps.name and i.sales_order != '' and i.sales_order is not null
		)
	""")
