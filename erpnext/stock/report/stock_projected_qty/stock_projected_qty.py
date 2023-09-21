# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _, scrub
from frappe.utils import flt, cint
from frappe.desk.query_report import group_report_data
from erpnext.stock.utils import update_included_uom_in_dict_report
from frappe.desk.reportview import build_match_conditions
from erpnext.stock.report.stock_balance.stock_balance import get_items_for_stock_report


def execute(filters=None):
	filters = frappe._dict(filters or {})
	show_item_name = frappe.defaults.get_global_default('item_naming_by') != "Item Name"

	items = get_items_for_stock_report(filters)
	bin_list = get_bin_list(filters, items)

	include_uom = filters.get("include_uom")
	item_map = get_item_map(bin_list, items, include_uom)

	data = []
	conversion_factors = []
	for bin in bin_list:
		item = item_map.get(bin.item_code)
		if not item:
			continue

		company = frappe.db.get_value("Warehouse", bin.warehouse, "company", cache=1)
		if filters.company and filters.company != company:
			continue

		alt_uom_size = item.alt_uom_size if filters.qty_field == "Contents Qty" and item.alt_uom else 1.0

		re_order_level = re_order_qty = 0

		for d in item.get("reorder_levels"):
			if d.warehouse == bin.warehouse:
				re_order_level = d.warehouse_reorder_level
				re_order_qty = d.warehouse_reorder_qty

		shortage_qty = 0
		if (re_order_level or re_order_qty) and re_order_level > bin.projected_qty:
			shortage_qty = re_order_level - flt(bin.projected_qty)

		data.append({
			"item_code": item.name,
			"item_name": item.item_name,
			"disable_item_formatter": cint(show_item_name),
			"item_group": item.item_group,
			"brand": item.brand,
			"warehouse": bin.warehouse,
			"uom": item.alt_uom or item.stock_uom if filters.qty_field == "Contents Qty" else item.stock_uom,
			"actual_qty": bin.actual_qty * alt_uom_size,
			"planned_qty": bin.planned_qty * alt_uom_size,
			"indented_qty": bin.indented_qty * alt_uom_size,
			"ordered_qty": bin.ordered_qty * alt_uom_size,
			"reserved_qty": bin.reserved_qty * alt_uom_size,
			"reserved_qty_for_production": bin.reserved_qty_for_production * alt_uom_size,
			"reserved_qty_for_sub_contract": bin.reserved_qty_for_sub_contract * alt_uom_size,
			"projected_qty": bin.projected_qty * alt_uom_size,
			"re_order_level": re_order_level * alt_uom_size,
			"re_order_qty": re_order_qty * alt_uom_size,
			"shortage_qty": shortage_qty * alt_uom_size
		})

		if include_uom:
			conversion_factors.append(flt(item.conversion_factor) * alt_uom_size)

	columns = get_columns(filters, show_item_name)

	update_included_uom_in_dict_report(columns, data, include_uom, conversion_factors)

	grouped_data = get_grouped_data(columns, data, filters, item_map)

	return columns, grouped_data


def get_grouped_data(columns, data, filters, item_map):
	group_by = []
	for i in range(2):
		group_label = filters.get("group_by_" + str(i + 1), "").replace("Group by ", "")

		if not group_label:
			continue
		elif group_label == "Item":
			group_field = "item_code"
		else:
			group_field = scrub(group_label)

		group_by.append(group_field)

	if not group_by:
		return data

	total_fields = [c['fieldname'] for c in columns if c['fieldtype'] in ['Float', 'Currency', 'Int']]

	def postprocess_group(group_object, grouped_by):
		if not group_object.group_field:
			group_object.totals['item_code'] = "'Total'"
		elif group_object.group_field == 'item_code':
			group_object.totals['item_code'] = group_object.group_value

			copy_fields = ['item_name', 'item_group', 'brand', 'uom', 'disable_item_formatter']
			for f in copy_fields:
				group_object.totals[f] = group_object.rows[0][f]
		else:
			group_object.totals['item_code'] = "'{0}: {1}'".format(group_object.group_label, group_object.group_value)

	return group_report_data(data, group_by, total_fields=total_fields, postprocess_group=postprocess_group)


def get_columns(filters, show_item_name=True):
	item_col_width = 150 if filters.get('group_by_1') or filters.get('group_by_2') else 100

	columns = [
		{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": item_col_width if show_item_name else 250},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 120},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Link", "options": "UOM", "width": 50},
		{"label": _("Actual Qty"), "fieldname": "actual_qty", "fieldtype": "Float", "width": 100, "convertible": "qty"},
		{"label": _("Projected Qty"), "fieldname": "projected_qty", "fieldtype": "Float", "width": 100, "convertible": "qty"},
		{"label": _("Ordered (PO)"), "fieldname": "ordered_qty", "fieldtype": "Float", "width": 110, "convertible": "qty"},
		{"label": _("Reserved (SO)"), "fieldname": "reserved_qty", "fieldtype": "Float", "width": 110, "convertible": "qty"},
		{"label": _("Planned (WO)"), "fieldname": "planned_qty", "fieldtype": "Float", "width": 110, "convertible": "qty"},
		{"label": _("Requested (MREQ)"), "fieldname": "indented_qty", "fieldtype": "Float", "width": 130, "convertible": "qty"},
		{"label": _("Reserved (WO)"), "fieldname": "reserved_qty_for_production", "fieldtype": "Float",
			"width": 110, "convertible": "qty"},
		{"label": _("Reserved (Subcontracting)"), "fieldname": "reserved_qty_for_sub_contract", "fieldtype": "Float",
			"width": 110, "convertible": "qty"},
		{"label": _("Reorder Level"), "fieldname": "re_order_level", "fieldtype": "Float", "width": 110, "convertible": "qty"},
		{"label": _("Reorder Qty"), "fieldname": "re_order_qty", "fieldtype": "Float", "width": 110, "convertible": "qty"},
		{"label": _("Shortage Qty"), "fieldname": "shortage_qty", "fieldtype": "Float", "width": 110, "convertible": "qty"},
		{"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group", "width": 100},
		{"label": _("Brand"), "fieldname": "brand", "fieldtype": "Link", "options": "Brand", "width": 100},
	]

	if not show_item_name:
		columns = [c for c in columns if c.get('fieldname') != 'item_name']

	return columns


def get_bin_list(filters, items):
	conditions = []

	if not items and items is not None:
		return []

	if items:
		items_condition = ", ".join([frappe.db.escape(name) for name in items])
		conditions.append(f"item_code in ({items_condition})")

	if filters.warehouse:
		warehouse_details = frappe.db.get_value("Warehouse", filters.warehouse, ["lft", "rgt"], as_dict=1)
		if warehouse_details:
			conditions.append("exists (select name from `tabWarehouse` wh \
				where wh.lft >= {0} and wh.rgt <= {1} and tabBin.warehouse = wh.name)".format(
				warehouse_details.lft, warehouse_details.rgt)
			)

	match_conditions = build_match_conditions("Bin")
	if match_conditions:
		conditions.append(match_conditions)

	bin_list = frappe.db.sql("""
		select item_code, warehouse,
			actual_qty, projected_qty,
			ordered_qty, reserved_qty,
			planned_qty, indented_qty,
			reserved_qty_for_production,
			reserved_qty_for_sub_contract
		from tabBin
		{conditions}
		order by item_code, warehouse
	""".format(conditions=" where " + " and ".join(conditions) if conditions else ""), as_dict=1)

	return bin_list


def get_item_map(bin_list, items, include_uom):
	item_map = frappe._dict()

	if not items:
		items = list(set([d.item_code for d in bin_list]))
	if not items:
		return item_map

	cf_field = cf_join = ""
	if include_uom:
		cf_field = ", ucd.conversion_factor"
		cf_join = "left join `tabUOM Conversion Detail` ucd on ucd.parent=item.name and ucd.uom=%(include_uom)s"

	items_data = frappe.db.sql("""
		select item.name, item.item_name, item.description, item.item_group, item.brand, item.item_source,
			item.stock_uom, item.alt_uom, item.alt_uom_size {cf_field}
		from `tabItem` item
		{cf_join}
		where item.name in %(item_codes)s
	""".format(cf_field=cf_field, cf_join=cf_join), {
		"item_codes": items, "include_uom": include_uom
	}, as_dict=True)

	item_reorder_data = frappe.db.sql("""
		select item_re.*
		from `tabItem Reorder` item_re
		inner join `tabItem` item on item_re.parent = item.name and item_re.parenttype = 'Item' 
		where item_re.parent in %s
	""", [items], as_dict=1)

	reorder_levels = frappe._dict()
	for ir in item_reorder_data:
		reorder_levels.setdefault(ir.parent, []).append(ir)

	for item in items_data:
		item["reorder_levels"] = reorder_levels.get(item.name) or []
		item_map[item.name] = item

	return item_map
