import frappe

def execute():
    """
    Update asset.asset_category_group
    by fetching it from asset_category.asset_category_group
    """

    frappe.db.sql("""
        UPDATE `tabAsset` a
        INNER JOIN `tabAsset Category` ac
            ON ac.name = a.asset_category
        SET a.asset_category_group = ac.asset_category_group
        WHERE
            ((a.asset_category IS NOT NULL) AND (ac.asset_category_group IS NOT NULL));
    """)