# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors and Contributors
# See license.txt

import unittest

import frappe


class TestPOSProfile(unittest.TestCase):
	pass


def make_pos_profile(**args):
	frappe.db.sql("delete from `tabPOS Profile`")

	args = frappe._dict(args)

	pos_profile = frappe.get_doc({
		"company": args.company or "_Test Company",
		"cost_center": args.cost_center or "_Test Cost Center - _TC",
		"currency": args.currency or "INR",
		"doctype": "POS Profile",
		"expense_account": args.expense_account or "_Test Account Cost for Goods Sold - _TC",
		"income_account":  args.income_account or "Sales - _TC",
		"name":  args.name or "_Test POS Profile",
		"naming_series": "_T-POS Profile-",
		"selling_price_list":  args.selling_price_list or "_Test Price List",
		"territory": args.territory or "_Test Territory",
		"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
		"warehouse":  args.warehouse or "_Test Warehouse - _TC",
		"write_off_account":  args.write_off_account or "_Test Write Off - _TC",
		"write_off_cost_center":  args.write_off_cost_center or "_Test Write Off Cost Center - _TC",
	})

	if not frappe.db.exists("POS Profile", args.name or "_Test POS Profile"):
		pos_profile.insert()

	return pos_profile
