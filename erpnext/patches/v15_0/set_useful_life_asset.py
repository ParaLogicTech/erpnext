
import frappe

def execute():
	frappe.reload_doc("assets", "doctype", "asset")
	frappe.db.sql("""
		UPDATE `tabAsset` a
		JOIN (
			SELECT
				parent AS asset_name,
				SUM(total_number_of_depreciations * frequency_of_depreciation) AS total_months
			FROM `tabAsset Finance Book`
			GROUP BY parent
		) fb ON fb.asset_name = a.name
		SET a.useful_life = ROUND(fb.total_months / 12, 3);
	""")