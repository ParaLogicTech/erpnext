# Copyright (c) 2018, Frappe and Contributors
# License: GNU General Public License v3. See license.txt

import frappe

def execute():
	frappe.db.sql("""update `tabDelivery Note` set print_without_amount=1""")
