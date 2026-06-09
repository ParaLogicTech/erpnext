import frappe


def execute():
	frappe.db.sql("""
		update `tabLanded Cost Voucher` lcv
		set lcv.party_name = lcv.party
		where lcv.party_name = '' or lcv.party_name is null
	""")

	frappe.db.sql("""
		update `tabLanded Cost Voucher` lcv
		inner join `tabSupplier` sup on sup.name = lcv.party and lcv.party_type = 'Supplier'
		set lcv.party_name = sup.supplier_name
	""")
