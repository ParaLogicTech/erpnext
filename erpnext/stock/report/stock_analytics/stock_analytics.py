# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _, scrub
from frappe.utils import getdate, flt
from erpnext.stock.report.stock_balance.stock_balance import (
	get_items_for_stock_report, get_stock_ledger_entries_for_stock_report
)
from erpnext.accounts.utils import get_fiscal_year


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns(filters)
	data = get_data(filters)
	chart = get_chart_data(columns, filters)

	return columns, data, None, chart


def get_columns(filters):
	columns = [
		{
			"label": _("Item Code"),
			"options": "Item",
			"fieldname": "name",
			"fieldtype": "Link",
			"width": 100
		},
		{
			"label": _("Item Name"),
			"fieldname": "item_name",
			"fieldtype": "Data",
			"width": 150
		},
		{
			"label": _("Item Group"),
			"options": "Item Group",
			"fieldname": "item_group",
			"fieldtype": "Link",
			"width": 120
		},
		{
			"label": _("UOM"),
			"fieldname": "uom",
			"fieldtype": "Data",
			"width": 50
		}]

	ranges = get_period_date_ranges(filters)

	for dummy, end_date in ranges:
		period = get_period(end_date, filters)

		columns.append({
			"label": _(period),
			"fieldname":scrub(period),
			"fieldtype": "Float",
			"width": 120
		})

	return columns


def get_period_date_ranges(filters):
		from dateutil.relativedelta import relativedelta
		from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)

		increment = {
			"Monthly": 1,
			"Quarterly": 3,
			"Half-Yearly": 6,
			"Yearly": 12
		}.get(filters.range, 1)

		periodic_daterange = []
		for dummy in range(1, 53, increment):
			if filters.range == "Weekly":
				period_end_date = from_date + relativedelta(days=6)
			else:
				period_end_date = from_date + relativedelta(months=increment, days=-1)

			if period_end_date > to_date:
				period_end_date = to_date
			periodic_daterange.append([from_date, period_end_date])

			from_date = period_end_date + relativedelta(days=1)
			if period_end_date == to_date:
				break

		return periodic_daterange


def get_period(posting_date, filters):
	months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

	if filters.range == 'Weekly':
		period = "Week " + str(posting_date.isocalendar()[1]) + " " + str(posting_date.year)
	elif filters.range == 'Monthly':
		period = str(months[posting_date.month - 1]) + " " + str(posting_date.year)
	elif filters.range == 'Quarterly':
		period = "Quarter " + str(((posting_date.month-1)//3)+1) +" " + str(posting_date.year)
	else:
		year = get_fiscal_year(posting_date, company=filters.company)
		period = str(year[2])

	return period


def get_periodic_data(sles, filters):
	periodic_data = {}
	for d in sles:
		period = get_period(d.posting_date, filters)
		bal_qty = 0

		if d.voucher_type == "Stock Reconciliation":
			if periodic_data.get(d.item_code):
				bal_qty = periodic_data[d.item_code]["balance"]

			qty_diff = d.qty_after_transaction - bal_qty
		else:
			qty_diff = d.actual_qty

		if filters["value_quantity"] == 'Quantity':
			value = qty_diff
		else:
			value = d.stock_value_difference

		periodic_data.setdefault(d.item_code, {}).setdefault(period, 0.0)
		periodic_data.setdefault(d.item_code, {}).setdefault("balance", 0.0)

		periodic_data[d.item_code]["balance"] += value
		periodic_data[d.item_code][period] = periodic_data[d.item_code]["balance"]

	return periodic_data


def get_data(filters):
	data = []
	items = get_items_for_stock_report(filters)
	sles = get_stock_ledger_entries_for_stock_report(filters, items)
	item_details = get_item_details(items, sles)
	periodic_data = get_periodic_data(sles, filters)
	ranges = get_period_date_ranges(filters)

	for dummy, item_data in item_details.items():
		row = {
			"name": item_data.name,
			"item_name": item_data.item_name,
			"item_group": item_data.item_group,
			"brand": item_data.brand,
			"uom": item_data.stock_uom,
			"disable_item_formatter": 1,
		}
		total = 0
		for dummy, end_date in ranges:
			period = get_period(end_date, filters)
			amount = flt(periodic_data.get(item_data.name, {}).get(period))
			row[scrub(period)] = amount
			total += amount
		row["total"] = total
		data.append(row)

	return data


def get_item_details(items, sles):
	item_map = {}

	if not items:
		items = list(set([d.item_code for d in sles]))
	if not items:
		return item_map

	item_data = frappe.db.sql("""
		select
			item.name, item.item_name, item.description, item.item_group, item.brand,
			item.stock_uom, item.alt_uom, item.alt_uom_size, item.disabled
		from `tabItem` item
		where item.name in %s
	""", [items], as_dict=1)

	for item in item_data:
		item_map[item.name] = item

	return item_map


def get_chart_data(columns, filters):
	labels = [d.get("label") for d in columns[4:]]
	chart = {
		"data": {
			"labels": labels,
			"datasets": []
		},
		"type": "line",
	}

	if filters.get("value_quantity") == "Value":
		chart["fieldtype"] = "Currency"
	else:
		chart["fieldtype"] = "Float"

	return chart




