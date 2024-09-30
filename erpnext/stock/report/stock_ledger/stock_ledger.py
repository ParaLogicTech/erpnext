# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _, scrub
from frappe.utils import cint, flt
from erpnext.stock.utils import update_included_uom_in_dict_report, has_valuation_read_permission
from erpnext.stock.report.stock_balance.stock_balance import get_items_for_stock_report
from erpnext.accounts.party import set_party_name_in_list
from frappe.desk.query_report import group_report_data
from frappe.desk.reportview import build_match_conditions


def execute(filters=None):
	show_amounts = has_valuation_read_permission()

	show_item_name = frappe.defaults.get_global_default('item_naming_by') != "Item Name"

	include_uom = filters.get("include_uom")
	items = get_items_for_stock_report(filters)
	sl_entries = get_stock_ledger_entries(filters, items)
	item_details = get_item_details(items, sl_entries, include_uom)
	opening_row = get_opening_balance(filters.item_code, filters.warehouse, filters.from_date)

	data = []
	conversion_factors = []
	if opening_row:
		data.append(opening_row)
		if include_uom:
			conversion_factor = 1
			alt_uom_size = 1
			if opening_row.get('item_code'):
				item_detail = item_details.get(opening_row.get('item_code'), {})
				conversion_factor = flt(item_detail.get('conversion_factor')) or 1
				alt_uom_size = item_detail.alt_uom_size if filters.qty_field == "Contents Qty" and item_detail.alt_uom else 1.0
			conversion_factors.append(conversion_factor * alt_uom_size)

	actual_qty = stock_value = 0

	for sle in sl_entries:
		item_detail = item_details[sle.item_code]
		alt_uom_size = item_detail.alt_uom_size if filters.qty_field == "Contents Qty" and item_detail.alt_uom else 1.0

		row = frappe._dict({
			"date": sle.date,
			"item_code": sle.item_code,
			"item_name": item_detail.item_name,
			"disable_item_formatter": cint(show_item_name),
			"item_group": item_detail.item_group,
			"brand": item_detail.brand,
			"description": item_detail.description,
			"warehouse": sle.warehouse,
			"party_type": sle.party_type,
			"party": sle.party,
			"uom": item_detail.alt_uom or item_detail.stock_uom if filters.qty_field == "Contents Qty" else item_detail.stock_uom,
			"actual_qty": sle.actual_qty * alt_uom_size,
			"qty_after_transaction": sle.qty_after_transaction * alt_uom_size,
			"batch_qty_after_transaction": sle.batch_qty_after_transaction * alt_uom_size,
			"packed_qty_after_transaction": sle.packed_qty_after_transaction * alt_uom_size,
			"voucher_type": sle.voucher_type,
			"voucher_no": sle.voucher_no,
			"batch_no": sle.batch_no,
			"serial_no": sle.serial_no,
			"packing_slip": sle.packing_slip,
			"project": sle.project,
			"company": sle.company
		})

		if row.get("packing_slip"):
			filters.has_packing_slip = True

		if show_amounts:
			row.update({
				"valuation_rate": sle.valuation_rate / alt_uom_size,
				"batch_valuation_rate": sle.batch_valuation_rate / alt_uom_size,
				"stock_value": sle.stock_value,
				"batch_stock_value": sle.batch_stock_value,
				"stock_value_difference": sle.stock_value_difference,
			})

			if sle.actual_qty:
				if sle.actual_qty > 0:
					row['transaction_rate'] = sle.incoming_rate
				else:
					row['transaction_rate'] = sle.stock_value_difference / sle.actual_qty
				row['transaction_rate'] /= alt_uom_size

		data.append(row)

		if include_uom:
			conversion_factors.append(flt(item_detail.conversion_factor) * alt_uom_size)

	columns = get_columns(filters, item_details, show_amounts, show_item_name)
	update_included_uom_in_dict_report(columns, data, include_uom, conversion_factors)

	set_party_name_in_list(data)

	data = get_grouped_data(filters, data)

	skip_total_row = False if filters.get('voucher_no') else True

	return columns, data, None, None, None, skip_total_row


def get_columns(filters, item_details, show_amounts=True, show_item_name=True):
	columns = [
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Datetime", "width": 95},
		{"label": _("Voucher Type"), "fieldname": "voucher_type", "width": 110},
		{"label": _("Voucher #"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 100},
		{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 100 if show_item_name else 150, "hide_if_filtered": 1},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 150, "hide_if_filtered": 1},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 100, "hide_if_filtered": 1},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Link", "options": "UOM", "width": 50},
		{"label": _("Qty"), "fieldname": "actual_qty", "fieldtype": "Float", "width": 60, "convertible": "qty"},
		{"label": _("Balance Qty"), "fieldname": "qty_after_transaction", "fieldtype": "Float", "width": 90, "convertible": "qty"},
		{"label": _("Batch"), "fieldname": "batch_no", "fieldtype": "Link", "options": "Batch", "width": 100, "is_batch": 1},
		{"label": _("Batch Qty"), "fieldname": "batch_qty_after_transaction", "fieldtype": "Float", "width": 90, "convertible": "qty", "is_batch": 1},
		{"label": _("Package"), "fieldname": "packing_slip", "fieldtype": "Link", "options": "Packing Slip", "width": 95, "is_packing_slip": 1},
		# {"label": _("Packed Qty"), "fieldname": "packed_qty_after_transaction", "fieldtype": "Float", "width": 90, "convertible": "qty", "is_packing_slip": 1},
	]

	if show_amounts:
		columns += [
			{"label": _("In/Out Rate"), "fieldname": "transaction_rate", "fieldtype": "Currency", "width": 100,
				"options": "Company:company:default_currency", "convertible": "rate"},
			{"label": _("In/Out Amount"), "fieldname": "stock_value_difference", "fieldtype": "Currency", "width": 100,
				"options": "Company:company:default_currency"},
			{"label": _("Valuation Rate"), "fieldname": "valuation_rate", "fieldtype": "Currency", "width": 100,
				"options": "Company:company:default_currency", "convertible": "rate"},
			{"label": _("Batch Valuation Rate"), "fieldname": "batch_valuation_rate", "fieldtype": "Currency", "width": 100,
				"options": "Company:company:default_currency", "convertible": "rate", "is_batch": 1},
			{"label": _("Balance Value"), "fieldname": "stock_value", "fieldtype": "Currency", "width": 110,
				"options": "Company:company:default_currency"},
			{"label": _("Batch Value"), "fieldname": "batch_stock_value", "fieldtype": "Currency", "width": 110,
				"options": "Company:company:default_currency", "is_batch": 1},
		]

	columns += [
		{"label": _("Party Type"), "fieldname": "party_type", "fieldtype": "Data", "width": 70, "hide_if_filtered": 1},
		{"label": _("Party"), "fieldname": "party", "fieldtype": "Dynamic Link", "options": "party_type", "width": 150, "hide_if_filtered": 1},
		{"label": _("Serial #"), "fieldname": "serial_no", "fieldtype": "Link", "options": "Serial No", "width": 100},
		{"label": _("Project"), "fieldname": "project", "fieldtype": "Link", "options": "Project", "width": 100, "hide_if_filtered": 1},
		{"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group", "width": 100, "hide_if_filtered": 1, "filter_fieldname": "item_code"},
		{"label": _("Brand"), "fieldname": "brand", "fieldtype": "Link", "options": "Brand", "width": 100, "hide_if_filtered": 1, "filter_fieldname": "item_code"},
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 110}
	]

	has_batch_no = any([d.has_batch_no for d in item_details.values()])
	if not has_batch_no:
		columns = [c for c in columns if not c.get('is_batch')]

	if not filters.has_packing_slip:
		columns = [c for c in columns if not c.get('is_packing_slip')]

	if not show_item_name:
		columns = [c for c in columns if c.get('fieldname') != 'item_name']

	return columns


def get_stock_ledger_entries(filters, items):
	item_conditions_sql = ''
	if items:
		item_conditions_sql = 'and item_code in ({})'\
			.format(', '.join([frappe.db.escape(i) for i in items]))

	return frappe.db.sql("""select concat_ws(" ", posting_date, posting_time) as date,
			item_code, warehouse, actual_qty, qty_after_transaction, incoming_rate, valuation_rate,
			stock_value, voucher_type, voucher_no, batch_no, serial_no, company, project, stock_value_difference,
			party_type, party,
			batch_qty_after_transaction, batch_stock_value, batch_valuation_rate,
			packing_slip, packed_qty_after_transaction
		from `tabStock Ledger Entry`
		where posting_date between %(from_date)s and %(to_date)s
			{sle_conditions}
			{item_conditions_sql}
			order by posting_date asc, posting_time asc, creation asc"""\
		.format(
			sle_conditions=get_sle_conditions(filters),
			item_conditions_sql=item_conditions_sql
		), filters, as_dict=1)


def get_item_details(items, sl_entries=None, include_uom=None):
	item_details = {}
	if not items and sl_entries:
		items = list(set([d.item_code for d in sl_entries]))

	if not items:
		return item_details

	cf_field = cf_join = ""
	if include_uom:
		cf_field = ", ucd.conversion_factor"
		cf_join = "left join `tabUOM Conversion Detail` ucd on ucd.parent=item.name and ucd.uom=%s" \
			% frappe.db.escape(include_uom)

	res = frappe.db.sql("""
		select
			item.name, item.item_name, item.description, item.item_group, item.brand,
			item.stock_uom, item.alt_uom, item.alt_uom_size, item.has_batch_no {cf_field}
		from
			`tabItem` item
			{cf_join}
		where
			item.name in ({item_codes})
	""".format(cf_field=cf_field, cf_join=cf_join, item_codes=','.join(['%s'] *len(items))), items, as_dict=1)

	for item in res:
		item_details.setdefault(item.name, item)

	return item_details


def get_sle_conditions(filters):
	conditions = []

	if filters.get("company"):
		conditions.append("company = %(company)s")

	if filters.get("warehouse"):
		warehouse_condition = get_warehouse_condition(filters.get("warehouse"))
		if warehouse_condition:
			conditions.append(warehouse_condition)
	if filters.get("voucher_no"):
		conditions.append("voucher_no=%(voucher_no)s")
	if filters.get("batch_no"):
		conditions.append("batch_no=%(batch_no)s")
	if filters.get("packing_slip"):
		conditions.append("(packing_slip=%(packing_slip)s or (voucher_type='Packing Slip' and voucher_no=%(packing_slip)s))")
	if filters.get("project"):
		conditions.append("project=%(project)s")
	if filters.get("party_type"):
		conditions.append("party_type=%(party_type)s")
	if filters.get("party"):
		conditions.append("party=%(party)s")

	if filters.get("serial_no"):
		conditions.append("""exists(select sr.name from `tabStock Ledger Entry Serial No` sr
			where sr.parent = `tabStock Ledger Entry`.name and sr.serial_no = %(serial_no)s)""")

	match_conditions = build_match_conditions("Stock Ledger Entry")
	if match_conditions:
		conditions.append(match_conditions)

	return "and {}".format(" and ".join(conditions)) if conditions else ""


def get_opening_balance(item_code, warehouse, from_date, from_time="00:00:00"):
	if not (item_code and warehouse and from_date):
		return frappe._dict()

	from erpnext.stock.stock_ledger import get_previous_sle
	last_entry = get_previous_sle({
		"item_code": item_code,
		"warehouse_condition": get_warehouse_condition(warehouse),
		"posting_date": from_date,
		"posting_time": from_time
	})
	row = frappe._dict()
	row["voucher_type"] = _("Opening")
	for f in ('qty_after_transaction', 'valuation_rate', 'stock_value'):
		row[f] = last_entry.get(f, 0)

	return row


def get_grouped_data(filters, data):
	if not filters.get("group_by"):
		return data

	group_by = []
	group_by_label = filters.group_by.replace("Group by ", "")
	if group_by_label == "Item-Warehouse":
		group_by += ['item_code', 'warehouse']
	elif group_by_label == "Item":
		group_by.append('item_code')
	elif group_by_label == "Party":
		group_by += ['party', 'party_type']
	elif group_by_label == "Voucher":
		group_by.append(('voucher_no', 'voucher_type'))
	else:
		group_by.append(scrub(group_by_label))

	def postprocess_group(group_object, grouped_by):
		if group_by_label in ["Item-Warehouse", "Party"] and len(grouped_by) < 2:
			return

		group_header = frappe._dict({})
		if 'item_code' in grouped_by and 'warehouse' in grouped_by and filters.from_date:
			opening_dt = frappe.utils.get_datetime(group_object.rows[0].date)
			opening_dt -= opening_dt.resolution
			group_header = get_opening_balance(group_object.item_code, group_object.warehouse, opening_dt.date(), opening_dt.time())

		if 'item_code' in grouped_by:
			group_object.item_name = group_object.rows[0].get('item_name')

		if 'party' in grouped_by:
			group_object.party_name = group_object.rows[0].get('party_name')

		for f, g in grouped_by.items():
			group_header[f] = g

		group_header._bold = True
		group_header._isGroupTotal = True
		group_object.rows.insert(0, group_header)

	return group_report_data(data, group_by, postprocess_group=postprocess_group)


def get_warehouse_condition(warehouse):
	warehouse_details = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"], as_dict=1)
	if warehouse_details:
		return " exists (select name from `tabWarehouse` wh \
			where wh.lft >= %s and wh.rgt <= %s and warehouse = wh.name)"%(warehouse_details.lft,
			warehouse_details.rgt)

	return ''


def get_item_group_condition(item_group):
	item_group_details = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=1)
	if item_group_details:
		return "item.item_group in (select ig.name from `tabItem Group` ig \
			where ig.lft >= %s and ig.rgt <= %s and item.item_group = ig.name)"%(item_group_details.lft,
			item_group_details.rgt)

	return ''
