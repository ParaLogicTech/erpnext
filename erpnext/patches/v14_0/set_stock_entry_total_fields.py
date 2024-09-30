import frappe


def execute():
	frappe.db.sql("""
		UPDATE `tabStock Entry` se
		SET
			total_qty = IFNULL((
				SELECT SUM(qty) FROM `tabStock Entry Detail` sed
				WHERE sed.parent = se.name AND IFNULL(sed.t_warehouse, '') != ''
			), 0),
			total_stock_qty = IFNULL((
				SELECT SUM(stock_qty) FROM `tabStock Entry Detail` sed
				WHERE sed.parent = se.name AND IFNULL(sed.t_warehouse, '') != ''
			), 0),
			total_alt_uom_qty = IFNULL((
				SELECT SUM(alt_uom_qty) FROM `tabStock Entry Detail` sed
				WHERE sed.parent = se.name AND IFNULL(sed.t_warehouse, '') != ''
			), 0)
	""")
