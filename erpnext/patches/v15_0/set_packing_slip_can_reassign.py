import frappe


def execute():
	frappe.db.sql("""
		update `tabPacking Slip`
		set original_customer = customer, original_customer_name = customer_name
	""")

	frappe.db.sql("""
		update `tabPacking Slip` ps
		set ps.can_reassign = 1
		where ps.status = 'In Stock' and ps.docstatus = 1 and not exists(
			select psi.name from `tabPacking Slip Item` psi
			where psi.parent = ps.name and (
				psi.sales_order != '' or psi.sales_order is not null
				or psi.source_packing_slip != '' or psi.source_packing_slip is not null
			)
		)
	""")
