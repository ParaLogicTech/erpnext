import frappe


def execute():
	frappe.reload_doc('buying', 'doctype', 'purchase_order_item')
	frappe.reload_doc('selling', 'doctype', 'sales_order_item')

	frappe.db.sql("""
		UPDATE `tabPurchase Order Item` poi
		JOIN (
			SELECT
				name,
				ROW_NUMBER() OVER (
					PARTITION BY parent
					ORDER BY idx, creation
				) AS new_idx
			FROM `tabPurchase Order Item`
		) t ON t.name = poi.name
		SET poi.idx = t.new_idx;
	""")

	frappe.db.sql("""
		UPDATE `tabSales Order Item` soi
		JOIN (
			SELECT
				name,
				ROW_NUMBER() OVER (
					PARTITION BY parent
					ORDER BY idx, creation
				) AS new_idx
			FROM `tabSales Order Item`
		) t ON t.name = soi.name
		SET soi.idx = t.new_idx;
	""")