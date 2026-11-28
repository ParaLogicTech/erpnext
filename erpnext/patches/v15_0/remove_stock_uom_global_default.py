import frappe


def execute():
	# Filled every new record's stock_uom field, including Item Overrides on Brand, Item Group and Item Source
	frappe.defaults.clear_default("stock_uom")
