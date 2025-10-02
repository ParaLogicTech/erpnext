import frappe


def execute():
	frappe.db.sql("""
		update `tabItem` i
		inner join `tabProduct Bundle` pb on pb.new_item_code = i.name
		set i.is_product_bundle = 1
	""")
