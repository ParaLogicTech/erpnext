# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import cint, getdate
from frappe import _

def execute(filters=None):
	if not filters: filters ={}

	days_since_last_order = filters.get("days_since_last_order")
	doctype = filters.get("doctype")

	if cint(days_since_last_order) <= 0:
		frappe.throw(_("'Days Since Last Order' must be greater than or equal to zero"))

	columns = get_columns()
	customers = get_sales_details(doctype, filters)

	data = []
	for cust in customers:
		if cint(cust[9]) >= cint(days_since_last_order):
			response = get_last_sales_amt(cust[1], doctype, filters)
			if response:
				cust.insert(8, response[0][0] or 0)
				cust.insert(11, response[0][1] or "")
				cust.insert(12, response[0][2] or "")
				cust.insert(13, response[0][3] or "")
				cust.insert(14, response[0][6] or "")
				cust.insert(15, response[0][4] or "")
				cust.insert(16, response[0][5] or "")
			else:
				cust.insert(8, 0)
				cust.insert(11, "")
				cust.insert(12, "")
				cust.insert(13, "")
				cust.insert(14, "")
				cust.insert(15, "")
				cust.insert(16, "")

			data.append(cust)
	data = apply_filters_for_last_order(data, filters)
	return columns, data

def apply_filters_for_last_order(data, filters):
	filtered_data = []
	
	for each_row in data:
		if filters.get("branch"):
			if each_row[15] != filters.get("branch"):
				continue
		if filters.get("cost_center"):
			if each_row[16] != filters.get("cost_center"):
				continue
		if filters.get("brand"):
			if each_row[11] != filters.get("brand"):
				continue
		
		if filters.get("from_date"):
			if each_row[9] < getdate(filters.get("from_date")):
				continue
		
		if filters.get("to_date"):
			if each_row[9] > getdate(filters.get("to_date")):
				continue

		filtered_data.append(each_row)
	return filtered_data

def get_sales_details(doctype, filters):
	cond = """sum(so.base_net_total) as 'total_order_considered',
			max(so.posting_date) as 'last_order_date',
			DATEDIFF(CURDATE(), max(so.posting_date)) as 'days_since_last_order'"""
	if doctype == "Sales Order":
		cond = """sum(if(so.status = "Stopped",
				so.base_net_total * so.per_delivered/100,
				so.base_net_total)) as 'total_order_considered',
			max(so.transaction_date) as 'last_order_date',
			DATEDIFF(CURDATE(), max(so.transaction_date)) as 'days_since_last_order'"""
	
	customer_cond = ""
	if filters.get("territory"):
		customer_cond += " and cust.territory = '{territory}'".format(territory = filters.get("territory"))
	
	if filters.get("customer_group"):
		customer_cond += " and cust.customer_group = '{customer_group}'".format(customer_group = filters.get("customer_group"))


	return frappe.db.sql("""select
			cust.creation as creation,
			cust.name,
			cust.customer_name,
			cust.territory,
			cust.customer_group,
			count(distinct(so.name)) as 'num_of_order',
			sum(base_net_total) as 'total_order_value', {0}
		from `tabCustomer` cust, `tab{1}` so
		where cust.name = so.customer and so.docstatus = 1 {2}
		group by cust.name
		order by 'days_since_last_order' desc """.format(cond, doctype, customer_cond), as_list=1)

def get_last_sales_amt(customer, doctype, filters):
	cond = "posting_date"
	if doctype =="Sales Order":
		cond = "transaction_date"

	res =  frappe.db.sql("""
		select 
			rev_doc.base_net_total,
			ti.brand,
			ti.name as applies_to_item,
			rev_doc.vehicle_chassis_no as vehicle_chassis_no,
			rev_doc.branch,
			rev_doc.cost_center,
			rev_doc.vehicle_last_odometer
		from 
			`tab{0}` rev_doc
		join 
			`tabItem` ti
		on
			ti.name = rev_doc.applies_to_item
		where rev_doc.customer = %s and rev_doc.docstatus = 1 order by {1} desc
		limit 1""".format(doctype, cond), customer)

	return res

def get_columns():
	return [
		_("Customer Creation") + ":Date Time:120",
		_("Customer") + ":Link/Customer:120",
		_("Customer Name") + ":Data:120",
		_("Territory") + "::120",
		_("Customer Group") + "::120",
		_("Number of Order") + "::120",
		_("Total Order Value") + ":Currency:120",
		_("Total Order Considered") + ":Currency:160",
		_("Last Order Amount") + ":Currency:160",
		_("Last Order Date") + ":Date:160",
		_("Days Since Last Order") + "::160",
		_("Vehicel Brand") + ":Link/Brand:160",
		_("Vehicel Model") + ":Link/Item:160",
		_("VIN Number") + ":Data:160",
		_("Last ODOMETER Reading") + ":Data:160",
		_("Location/Branch") + ":Link/Branch:160",
		_("Cost Center") + ":Link/Cost Center:160",
	]
