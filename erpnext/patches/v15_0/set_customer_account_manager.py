import frappe


def execute():
	data = frappe.db.sql("""
		select parent as customer, sales_person, allocated_percentage
		from `tabSales Team`
		where parenttype = 'Customer' and sales_person is not null and sales_person != ''
		order by allocated_percentage desc
	""", as_dict=1)

	customer_sales_team_map = {}
	for d in data:
		customer_sales_team_map.setdefault(d.customer, []).append(d)

	customers_without_account_manager = frappe.db.sql_list("""
		select name from `tabCustomer` where account_manager is null or account_manager = ''
	""")

	for customer in customers_without_account_manager:
		if not customer_sales_team_map.get(customer):
			continue

		account_manager = customer_sales_team_map[customer][0].sales_person
		if not account_manager:
			continue

		frappe.db.set_value("Customer", customer, "account_manager", account_manager, update_modified=False)
