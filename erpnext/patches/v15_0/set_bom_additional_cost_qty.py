import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	frappe.reload_doctype("BOM Additional Cost")
	frappe.reload_doctype("BOM Item")
	frappe.reload_doctype("BOM")
	frappe.reload_doctype("Work Order")

	frappe.db.sql("""
		update `tabBOM Additional Cost` bac
		inner join `tabBOM` bom on bom.name = bac.parent
		set bac.qty = bom.quantity
	""")

	frappe.db.sql("""
		update `tabBOM`
		set
			total_material_cost = raw_material_cost,
			base_total_material_cost = base_raw_material_cost
	""")

	frappe.db.sql("""
		update `tabBOM`
		set
			unit_raw_material_cost = raw_material_cost / quantity,
			base_unit_raw_material_cost = base_raw_material_cost / quantity,
			unit_packaging_material_cost = packaging_material_cost / quantity,
			base_unit_packaging_material_cost = base_packaging_material_cost / quantity,
			unit_material_cost = total_material_cost / quantity,
			base_unit_material_cost = base_total_material_cost / quantity,
			unit_operating_cost = total_operating_cost / quantity,
			base_unit_operating_cost = base_total_operating_cost / quantity,
			unit_scrap_material_cost = scrap_material_cost / quantity,
			base_unit_scrap_material_cost = base_scrap_material_cost / quantity,
			unit_cost = total_cost / quantity,
			base_unit_cost = base_total_cost / quantity
	""")

	rename_field("Work Order", "raw_material_cost", "total_material_cost")
