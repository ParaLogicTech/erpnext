import frappe

def execute():
    if not frappe.db.exists("Asset Category Group",{"parent_asset_category_group":""}):
        asset_category_group_root_record = [{'doctype': 'Asset Category Group', 
                'asset_category_group_name': frappe._('All Asset Category Group'), 
                'is_group': 1, 'name': frappe._('All Asset Category Group'), 
                'parent_asset_category_group': '', 'lft':1}]
        from frappe.desk.page.setup_wizard.setup_wizard import make_records
        make_records(asset_category_group_root_record)
        frappe.db.commit()