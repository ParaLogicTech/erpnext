# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe

def execute():
	"""Unset any invalid account_manager links in Customer doctype that don't reference a valid Sales Person"""
	
	# Get all customers that have an account_manager set
	customers = frappe.get_all("Customer", 
		filters={"account_manager": ["is", "set"]},
		fields=["name", "account_manager"]
	)

	# Get all valid sales persons
	valid_sales_persons = set(frappe.get_all("Sales Person", pluck="name"))

	# Update customers with invalid account_manager
	for customer in customers:
		if customer.account_manager not in valid_sales_persons:
			frappe.db.set_value("Customer", customer.name, "account_manager", None)
			
			# Log the change
			frappe.logger().info(
				f"Unset invalid account_manager '{customer.account_manager}' in Customer '{customer.name}'"
			)