import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	rename_field("Purchase Receipt", "rejected_warehouse", "default_rejected_warehouse")
	rename_field("Purchase Invoice", "rejected_warehouse", "default_rejected_warehouse")

	rename_field("Packing Slip", "rejected_warehouse", "default_rejected_warehouse")
	frappe.db.sql("""
		update `tabPacking Slip Item` i
		inner join `tabPacking Slip` p on p.name = i.parent
		set i.rejected_warehouse = p.default_rejected_warehouse
	""")
