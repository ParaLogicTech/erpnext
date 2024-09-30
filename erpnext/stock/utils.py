# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe, erpnext
from frappe import _
import json
from frappe.utils import flt, cstr, nowdate, nowtime

from six import string_types, iteritems


class InvalidWarehouseCompany(frappe.ValidationError): pass


def get_stock_value_from_bin(warehouse=None, item_code=None):
	values = {}
	conditions = ""
	if warehouse:
		conditions += """ and `tabBin`.warehouse in (
						select w2.name from `tabWarehouse` w1
						join `tabWarehouse` w2 on
						w1.name = %(warehouse)s
						and w2.lft between w1.lft and w1.rgt
						) """

		values['warehouse'] = warehouse

	if item_code:
		conditions += " and `tabBin`.item_code = %(item_code)s"

		values['item_code'] = item_code

	query = """select sum(stock_value) from `tabBin`, `tabItem` where 1 = 1
		and `tabItem`.name = `tabBin`.item_code and ifnull(`tabItem`.disabled, 0) = 0 %s""" % conditions

	stock_value = frappe.db.sql(query, values)

	return stock_value


def get_stock_value_on(warehouse=None, posting_date=None, item_code=None):
	if not posting_date: posting_date = nowdate()

	values, condition = [posting_date], ""

	if warehouse:

		lft, rgt, is_group = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt", "is_group"])

		if is_group:
			values.extend([lft, rgt])
			condition += "and exists (\
				select name from `tabWarehouse` wh where wh.name = sle.warehouse\
				and wh.lft >= %s and wh.rgt <= %s)"

		else:
			values.append(warehouse)
			condition += " AND warehouse = %s"

	if item_code:
		values.append(item_code)
		condition += " AND item_code = %s"

	stock_ledger_entries = frappe.db.sql("""
		SELECT item_code, stock_value, name, warehouse
		FROM `tabStock Ledger Entry` sle
		WHERE posting_date <= %s {0}
		ORDER BY posting_date DESC, posting_time DESC, creation DESC
	""".format(condition), values, as_dict=1)

	sle_map = {}
	for sle in stock_ledger_entries:
		if not (sle.item_code, sle.warehouse) in sle_map:
			sle_map[(sle.item_code, sle.warehouse)] = flt(sle.stock_value)

	return sum(sle_map.values())


def get_stock_balance(
	item_code,
	warehouse,
	batch_no=None,
	posting_date=None,
	posting_time=None,
	with_valuation_rate=False,
	with_serial_no=False,
):
	"""Returns stock balance quantity at given warehouse on given posting date or current date.

	If `with_valuation_rate` is True, will return tuple (qty, rate)"""

	from erpnext.stock.stock_ledger import get_previous_sle, get_serial_nos_after_sle

	if not posting_date:
		posting_date = nowdate()
	if not posting_time:
		posting_time = nowtime()

	args = {
		"item_code": item_code,
		"warehouse": warehouse,
		"posting_date": posting_date,
		"posting_time": posting_time,
		"batch_no": batch_no
	}
	last_entry = get_previous_sle(args)

	out = frappe._dict({
		"qty_after_transaction": last_entry.qty_after_transaction if last_entry else 0,
	})

	if batch_no:
		out["batch_qty_after_transaction"] = last_entry.batch_qty_after_transaction if last_entry else 0

	if with_valuation_rate:
		if last_entry:
			out["valuation_rate"] = last_entry.batch_valuation_rate if batch_no else last_entry.valuation_rate
			out["stock_value"] = last_entry.batch_stock_value if batch_no else last_entry.stock_value
		else:
			out["valuation_rate"] = 0
			out["stock_value"] = 0

	if with_serial_no:
		serial_nos = ""
		if last_entry:
			serial_nos = last_entry.get("serial_no")
			if serial_nos and len(get_serial_nos_data(serial_nos)) < last_entry.qty_after_transaction:
				serial_nos = get_serial_nos_after_sle(args)

		out["serial_nos"] = cstr(serial_nos)

	return out


def get_unpacked_balance_qty(item_code, warehouse, batch_no=None, posting_date=None, posting_time=None):
	from erpnext.stock.stock_ledger import get_previous_sle

	if not posting_date:
		posting_date = nowdate()
	if not posting_time:
		posting_time = nowtime()

	args = {
		"item_code": item_code,
		"warehouse": warehouse,
		"posting_date": posting_date,
		"posting_time": posting_time,
		"batch_no": batch_no,
	}

	last_entry = get_previous_sle(args, packing_slip_sle=True)
	return last_entry.packed_qty_after_transaction if last_entry else 0


def get_serial_nos_data(serial_nos):
	from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos
	return get_serial_nos(serial_nos)


@frappe.whitelist()
def get_latest_stock_qty(item_code, warehouse=None):
	values, condition = [item_code], ""
	if warehouse:
		is_group = frappe.db.get_value("Warehouse", warehouse, "is_group", cache=1)
		if is_group:
			lft, rgt = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"])
			values.extend([lft, rgt])
			condition += "and exists (\
				select name from `tabWarehouse` wh where wh.name = tabBin.warehouse\
				and wh.lft >= %s and wh.rgt <= %s)"
		else:
			values.append(warehouse)
			condition += " AND warehouse = %s"

	actual_qty = frappe.db.sql("""
		select sum(actual_qty)
		from tabBin
		where item_code=%s {0}
	""".format(condition), values)

	return flt(actual_qty[0][0]) if actual_qty else 0


def get_latest_stock_balance():
	bin_map = {}
	for d in frappe.db.sql("""SELECT item_code, warehouse, stock_value as stock_value
		FROM tabBin""", as_dict=1):
			bin_map.setdefault(d.warehouse, {}).setdefault(d.item_code, flt(d.stock_value))

	return bin_map


def get_bin(item_code, warehouse):
	bin = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse})

	if not bin:
		bin_obj = frappe.get_doc({
			"doctype": "Bin",
			"item_code": item_code,
			"warehouse": warehouse,
		})
		bin_obj.flags.ignore_permissions = 1
		bin_obj.insert()
	else:
		bin_obj = frappe.get_cached_doc('Bin', bin)

	bin_obj.flags.ignore_permissions = True
	return bin_obj


def update_bin(args, allow_negative_stock=False, via_landed_cost_voucher=False):
	is_stock_item = frappe.db.get_value('Item', args.get("item_code"), 'is_stock_item', cache=1)
	if is_stock_item:
		bin = get_bin(args.get("item_code"), args.get("warehouse"))
		bin.update_stock(args, allow_negative_stock, via_landed_cost_voucher)
		return bin
	else:
		frappe.msgprint(_("Item {0} ignored since it is not a stock item").format(args.get("item_code")))


@frappe.whitelist()
def get_incoming_rate(args, raise_error_if_no_rate=True):
	"""Get Incoming Rate based on valuation method"""
	from erpnext.stock.stock_ledger import get_previous_sle, get_valuation_rate
	if isinstance(args, string_types):
		args = json.loads(args)

	in_rate = 0
	if (args.get("serial_no") or "").strip():
		in_rate = get_avg_purchase_rate(args.get("serial_no"))
	else:
		valuation_method, batch_wise_valuation = get_valuation_method(args.get("item_code"))
		previous_sle = get_previous_sle(args)
		if valuation_method == 'FIFO':
			if previous_sle:
				previous_stock_queue = json.loads(previous_sle.get('stock_queue', '[]') or '[]')
				in_rate = get_fifo_rate(previous_stock_queue, args.get("qty") or 0) if previous_stock_queue else 0
		elif valuation_method == 'Moving Average':
			if batch_wise_valuation:
				in_rate = previous_sle.get('batch_valuation_rate') or 0
			else:
				in_rate = previous_sle.get('valuation_rate') or 0

	if not in_rate:
		voucher_no = args.get('voucher_no') or args.get('name')
		in_rate = get_valuation_rate(args.get('item_code'), args.get('warehouse'),
			args.get('voucher_type'), voucher_no, args.get('batch_no'), args.get('allow_zero_valuation'),
			currency=erpnext.get_company_currency(args.get('company')), company=args.get('company'),
			raise_error_if_no_rate=raise_error_if_no_rate)

	return in_rate


def get_avg_purchase_rate(serial_nos):
	"""get average value of serial numbers"""

	serial_nos = get_valid_serial_nos(serial_nos)
	return flt(frappe.db.sql("""select avg(purchase_rate) from `tabSerial No`
		where name in (%s)""" % ", ".join(["%s"] * len(serial_nos)),
		tuple(serial_nos))[0][0])


def get_valuation_method(item_code):
	def generator():
		"""get valuation method from item or default"""
		val_method, has_batch_no, has_serial_no = frappe.db.get_value('Item', item_code,
			['valuation_method', 'has_batch_no', 'has_serial_no'])

		if not val_method:
			val_method = frappe.db.get_single_value("Stock Settings", "valuation_method", cache=True) or "FIFO"

		batch_wise_valuation = bool(has_batch_no and not has_serial_no)
		if batch_wise_valuation:
			val_method = "Moving Average"  # only Moving Average within batch is supported for now

		return val_method, batch_wise_valuation

	return frappe.local_cache("item_valuation_method", item_code, generator)


def get_fifo_rate(previous_stock_queue, qty):
	"""get FIFO (average) Rate from Queue"""
	if flt(qty) >= 0:
		total = sum(f[0] for f in previous_stock_queue)
		return sum(flt(f[0]) * flt(f[1]) for f in previous_stock_queue) / flt(total) if total else 0.0
	else:
		available_qty_for_outgoing, outgoing_cost = 0, 0
		qty_to_pop = abs(flt(qty))
		while qty_to_pop and previous_stock_queue:
			batch = previous_stock_queue[0]
			if 0 < batch[0] <= qty_to_pop:
				# if batch qty > 0
				# not enough or exactly same qty in current batch, clear batch
				available_qty_for_outgoing += flt(batch[0])
				outgoing_cost += flt(batch[0]) * flt(batch[1])
				qty_to_pop -= batch[0]
				previous_stock_queue.pop(0)
			else:
				# all from current batch
				available_qty_for_outgoing += flt(qty_to_pop)
				outgoing_cost += flt(qty_to_pop) * flt(batch[1])
				batch[0] -= qty_to_pop
				qty_to_pop = 0

		return outgoing_cost / available_qty_for_outgoing


def get_valid_serial_nos(sr_nos, qty=0, item_code=''):
	"""split serial nos, validate and return list of valid serial nos"""
	# TODO: remove duplicates in client side
	serial_nos = cstr(sr_nos).strip().replace(',', '\n').split('\n')

	valid_serial_nos = []
	for val in serial_nos:
		if val:
			val = val.strip()
			if val in valid_serial_nos:
				frappe.throw(_("Serial number {0} entered more than once").format(val))
			else:
				valid_serial_nos.append(val)

	if qty and len(valid_serial_nos) != abs(qty):
		frappe.throw(_("{0} valid serial nos for Item {1}").format(abs(qty), item_code))

	return valid_serial_nos


def validate_warehouse_company(warehouse, company):
	warehouse_company = frappe.db.get_value("Warehouse", warehouse, "company", cache=1)
	if warehouse_company and warehouse_company != company:
		frappe.throw(_("Warehouse {0} does not belong to company {1}").format(warehouse, company),
			InvalidWarehouseCompany)


def is_group_warehouse(warehouse):
	if frappe.db.get_value("Warehouse", warehouse, "is_group", cache=1):
		frappe.throw(_("Group node warehouse is not allowed to select for transactions"))


def get_available_serial_nos(item_code, warehouse):
	return frappe.get_all("Serial No", filters={'item_code': item_code,
		'warehouse': warehouse, 'delivery_document_no': ''}) or []


def format_item_name(doc):
	if doc.get('item_name') and doc.get('item_name') != doc.get('item_code'):
		if doc.get('hide_item_code'):
			return doc.get('item_name')
		else:
			return "{0}: {1}".format(doc.get('item_code'), doc.get('item_name')) if doc.get('item_name')\
				else doc.get('item_code')
	else:
		return doc.get('item_code')


def update_included_uom_in_list_report(columns, result, include_uom, conversion_factors):
	if not include_uom or not conversion_factors:
		return

	convertible_cols = {}
	for col_idx in reversed(range(0, len(columns))):
		col = columns[col_idx]
		if isinstance(col, dict) and col.get("convertible") in ['rate', 'qty']:
			convertible_cols[col_idx] = col['convertible']
			columns.insert(col_idx+1, col.copy())
			columns[col_idx+1]['fieldname'] += "_alt"
			if convertible_cols[col_idx] == 'rate':
				columns[col_idx+1]['label'] += " (per {})".format(include_uom)
			else:
				columns[col_idx+1]['label'] += " ({})".format(include_uom)

	for row_idx, row in enumerate(result):
		new_row = []
		for col_idx, d in enumerate(row):
			new_row.append(d)
			if col_idx in convertible_cols:
				if conversion_factors[row_idx]:
					if convertible_cols[col_idx] == 'rate':
						new_row.append(flt(d) * conversion_factors[row_idx])
					else:
						new_row.append(flt(d) / conversion_factors[row_idx])
				else:
					new_row.append(None)

		result[row_idx] = new_row


def update_included_uom_in_dict_report(columns, result, include_uom, conversion_factors):
	if not include_uom or not conversion_factors:
		return

	convertible_cols = {}
	for col_idx in reversed(range(0, len(columns))):
		col = columns[col_idx]
		if isinstance(col, dict) and col.get('fieldname') and col.get("convertible") in ['rate', 'qty']:
			convertible_cols[col['fieldname']] = col['convertible']
			columns.insert(col_idx+1, col.copy())
			columns[col_idx+1]['fieldname'] += "_alt"
			if convertible_cols[col['fieldname']] == 'rate':
				columns[col_idx+1]['label'] += " (per {})".format(include_uom)
			else:
				columns[col_idx+1]['label'] += " ({})".format(include_uom)

	for row_idx, row in enumerate(result):
		for fieldname, conversion_type in iteritems(convertible_cols):
			if conversion_factors[row_idx]:
				if conversion_type == 'rate':
					row[fieldname + "_alt"] = flt(row.get(fieldname)) * conversion_factors[row_idx]
				else:
					row[fieldname + "_alt"] = flt(row.get(fieldname)) / conversion_factors[row_idx]


def has_valuation_read_permission():
	show_amounts_role = frappe.db.get_single_value("Stock Settings", "restrict_stock_valuation_to_role")
	show_amounts = not show_amounts_role or show_amounts_role in frappe.get_roles()
	return show_amounts
