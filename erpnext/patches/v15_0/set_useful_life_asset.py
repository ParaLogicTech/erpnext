
import frappe

def execute():
	frappe.reload_doc("assets", "doctype", "asset")
	frappe.db.sql("""
		UPDATE `tabAsset` a
		JOIN (
			SELECT
				parent AS asset_name,
				total_number_of_depreciations,
				frequency_of_depreciation
			FROM (
				SELECT
					parent,
					total_number_of_depreciations,
					frequency_of_depreciation,
					ROW_NUMBER() OVER (
						PARTITION BY parent
						ORDER BY idx
					) AS rn
				FROM `tabAsset Finance Book`
			) t
			WHERE rn = 1
		) fb ON fb.asset_name = a.name
		SET
			a.useful_life = ROUND((fb.total_number_of_depreciations * fb.frequency_of_depreciation) / 12, 3),
			a.total_number_of_depreciations = fb.total_number_of_depreciations;
	""")