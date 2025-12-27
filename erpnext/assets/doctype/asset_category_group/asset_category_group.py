# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils.nestedset import NestedSet, get_root_of

class AssetCategoryGroup(NestedSet):
	nsm_parent_field = 'parent_asset_category_group'

	def validate(self):
		if not self.parent_asset_category_group:
			self.parent_asset_category_group = get_root_of("Asset Category Group")

	def on_update(self):
		super(AssetCategoryGroup, self).on_update()
		self.validate_one_root()

def get_parent_asset_category_groups(asset_category_group):
	lft, rgt = frappe.db.get_value("Asset Category Group", asset_category_group, ['lft', 'rgt'])
	return frappe.db.sql("""
		select name
		from `tabAsset Category Group`
		where lft <= %s and rgt >= %s
		order by lft asc
	""", (lft, rgt), as_dict=True)

def get_asset_category_group_subtree(asset_category_group, cache=True):
	def generator():
		return frappe.get_all("Asset Category Group", filters={"name": ["subtree of", asset_category_group]}, pluck="name")

	if cache:
		return frappe.local_cache("get_customer_group_subtree", asset_category_group, generator)
	else:
		return generator()

def on_doctype_update():
	frappe.db.add_index("Asset Category Group", ["lft", "rgt"])
