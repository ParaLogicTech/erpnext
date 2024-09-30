# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname, revert_series_if_last
from frappe.utils import flt, cint, get_link_to_form, cstr, round_down
from frappe.utils.data import add_days
import json


class UnableToSelectBatchError(frappe.ValidationError):
	pass


class Batch(Document):
	def autoname(self):
		"""Generate random ID for batch if not specified"""
		if not self.batch_id:
			create_new_batch = frappe.get_cached_value("Item", self.item, "create_new_batch")
			if create_new_batch:
				batch_no_series = get_batch_naming_series(self.item)
				if batch_no_series:
					self.batch_id = make_autoname(batch_no_series, self.doctype, self)
				else:
					self.batch_id = generate_batch_no_hash()
			else:
				frappe.throw(_('Batch ID is mandatory'), frappe.MandatoryError)

		self.name = self.batch_id

	def onload(self):
		self.image = frappe.db.get_value('Item', self.item, 'image')

	def after_delete(self):
		series = get_batch_naming_series(self.item)
		if series:
			revert_series_if_last(series, self.name, self)

	def validate(self):
		self.item_has_batch_enabled()

	def item_has_batch_enabled(self):
		if frappe.db.get_value("Item", self.item, "has_batch_no", cache=1) == 0:
			frappe.throw(_("The selected item cannot have Batch"))

	def before_save(self):
		has_expiry_date, shelf_life_in_days = frappe.db.get_value('Item', self.item, ['has_expiry_date', 'shelf_life_in_days'])
		if not self.expiry_date and has_expiry_date and shelf_life_in_days:
			self.expiry_date = add_days(self.manufacturing_date, shelf_life_in_days)

		if has_expiry_date and not self.expiry_date:
			frappe.throw(msg=_("Please set {0} for Batched Item {1}, which is used to set {2} on Submit.") \
				.format(frappe.bold("Shelf Life in Days"),
					get_link_to_form("Item", self.item),
					frappe.bold("Batch Expiry Date")),
				title=_("Expiry Date Mandatory"))


def get_batch_naming_series(item_code):
	item_details = None
	if item_code:
		item_details = frappe.get_cached_value("Item", item_code, ["create_new_batch", "batch_number_series"], as_dict=True)

	if item_details and item_details.create_new_batch and item_details.batch_number_series:
		return format_batch_series(item_details.batch_number_series)
	elif batches_use_naming_series():
		return get_default_batch_series()


def get_default_batch_series():
	prefix = get_default_batch_prefix()
	return format_batch_series(prefix)


def get_default_batch_prefix():
	naming_series_prefix = frappe.db.get_single_value("Stock Settings", "naming_series_prefix")
	if not naming_series_prefix:
		naming_series_prefix = "BATCH-"

	return naming_series_prefix


def format_batch_series(prefix):
	"""
	Make naming series key for a Batch.

	Naming series key is in the format [prefix].[#####]
	:param prefix: Naming series prefix gotten from Stock Settings
	:return: The derived key. If no prefix is given, an empty string is returned
	"""
	prefix = cstr(prefix)
	if not prefix:
		return ""

	if not prefix.find('#'):
		prefix = prefix + '.#####'

	return prefix


def generate_batch_no_hash():
	hash_name = None
	while not hash_name:
		hash_name = frappe.generate_hash(length=7).upper()
		if frappe.db.exists('Batch', hash_name):
			hash_name = None

	return hash_name


def batches_use_naming_series():
	use_naming_series = cint(frappe.db.get_single_value('Stock Settings', 'use_naming_series'))
	return bool(use_naming_series)


@frappe.whitelist()
def get_batch_qty(batch_no=None, warehouse=None, item_code=None, posting_date=None, posting_time=None):
	"""Returns batch actual qty if warehouse is passed,
		or returns dict of qty by warehouse if warehouse is None

	The user must pass either batch_no or batch_no + warehouse or item_code + warehouse

	:param batch_no: Optional - give qty for this batch no
	:param warehouse: Optional - give qty for this warehouse
	:param item_code: Optional - give qty for this item"""

	out = 0

	date_cond = ""
	if posting_date and posting_time:
		date_cond = " and (posting_date, posting_time) <= ('{0}', '{1}')".format(posting_date, posting_time)

	if batch_no and warehouse:
		out = flt(frappe.db.sql("""
			select sum(actual_qty)
			from `tabStock Ledger Entry`
			where warehouse=%s and batch_no=%s {0}
		""".format(date_cond), (warehouse, batch_no))[0][0] or 0)

	if batch_no and not warehouse:
		out = frappe.db.sql("""
			select warehouse, sum(actual_qty) as qty
			from `tabStock Ledger Entry`
			where batch_no = %s {0}
			group by warehouse
		""".format(date_cond), batch_no, as_dict=1)

	if not batch_no and item_code and warehouse:
		out = frappe.db.sql("""
			select batch_no, sum(actual_qty) as qty
			from `tabStock Ledger Entry`
			where item_code = %s and warehouse=%s {0}
			group by batch_no
		""".format(date_cond), (item_code, warehouse), as_dict=1)

	return out


def get_batch_qty_on(batch_no, warehouse, posting_date, posting_time):
	res = frappe.db.sql("""
		select sum(actual_qty)
		from `tabStock Ledger Entry`
		where (posting_date, posting_time) <= (%s, %s)
			and ifnull(is_cancelled, 'No') = 'No' and warehouse = %s and batch_no = %s
	""", (posting_date, posting_time, warehouse, batch_no))

	return flt(res[0][0]) if res else 0.0


@frappe.whitelist()
def get_batches_by_oldest(item_code, warehouse):
	"""Returns the oldest batch and qty for the given item_code and warehouse"""
	batches = get_batch_qty(item_code=item_code, warehouse=warehouse)
	batches_dates = [[batch, frappe.get_value('Batch', batch.batch_no, 'expiry_date')] for batch in batches]
	batches_dates.sort(key=lambda tup: tup[1])
	return batches_dates


@frappe.whitelist()
def split_batch(batch_no, item_code, warehouse, qty, new_batch_id=None):
	"""Split the batch into a new batch"""
	batch = frappe.get_doc(dict(doctype='Batch', item=item_code, batch_id=new_batch_id)).insert()

	company = frappe.db.get_value('Stock Ledger Entry', dict(
			item_code=item_code,
			batch_no=batch_no,
			warehouse=warehouse
		), ['company'])

	stock_entry = frappe.get_doc(dict(
		doctype='Stock Entry',
		purpose='Repack',
		company=company,
		items=[
			dict(
				item_code=item_code,
				qty=float(qty or 0),
				s_warehouse=warehouse,
				batch_no=batch_no
			),
			dict(
				item_code=item_code,
				qty=float(qty or 0),
				t_warehouse=warehouse,
				batch_no=batch.name
			),
		]
	))
	stock_entry.set_stock_entry_type()
	stock_entry.insert()
	stock_entry.submit()

	return batch.name


def set_batch_nos(doc, warehouse_field, throw=False):
	"""Automatically select `batch_no` for outgoing items in item table"""
	for d in doc.items:
		qty = d.get('stock_qty') or d.get('transfer_qty') or d.get('qty') or 0
		has_batch_no = frappe.db.get_value('Item', d.item_code, 'has_batch_no')
		warehouse = d.get(warehouse_field, None)
		if has_batch_no and warehouse and qty > 0:
			if not d.batch_no:
				d.batch_no = get_batch_no(d.item_code, warehouse, qty, throw)
			else:
				batch_qty = get_batch_qty(batch_no=d.batch_no, warehouse=warehouse)
				if flt(batch_qty, d.precision("qty")) < flt(qty, d.precision("qty")) and throw:
					frappe.throw(_("Row #{0}: The batch {1} has only {2} qty. Please select another batch which has {3} qty available or split the row into multiple rows, to deliver/issue from multiple batches").format(d.idx, d.batch_no, batch_qty, qty))


def auto_select_and_split_batches(doc, warehouse_field, additional_group_fields=None):
	def get_key(data):
		key_fieldnames = ["item_code", "uom", warehouse_field]
		if additional_group_fields:
			if isinstance(additional_group_fields, list):
				key_fieldnames += additional_group_fields
			else:
				key_fieldnames.append(additional_group_fields)

		return tuple(cstr(data.get(f)) for f in key_fieldnames)

	group_qty_map = {}
	for d in doc.items:
		has_batch_no = d.get("item_code") and frappe.get_cached_value("Item", d.item_code, "has_batch_no")
		warehouse = d.get(warehouse_field)
		if has_batch_no and warehouse and not d.get("packing_slip") and not d.get("source_packing_slip"):
			key = get_key(d)
			group_qty_map.setdefault(key, 0)
			group_qty_map[key] += flt(d.get('qty'))

	# no lines valid for batch no selection
	if not group_qty_map:
		return

	visited = set()
	to_remove = []
	for d in doc.items:
		has_batch_no = d.get("item_code") and frappe.get_cached_value("Item", d.item_code, "has_batch_no")
		warehouse = d.get(warehouse_field)
		if has_batch_no and warehouse and not d.get("packing_slip") and not d.get("source_packing_slip"):
			key = get_key(d)
			if key not in visited:
				visited.add(key)
				d.batch_no = None
				d.qty = flt(group_qty_map.get(key))
			else:
				to_remove.append(d)

	for d in to_remove:
		doc.remove(d)

	updated_rows = []
	batches_used = {}
	for d in doc.items:
		updated_rows.append(d)

		has_batch_no = d.get("item_code") and frappe.get_cached_value("Item", d.item_code, "has_batch_no")
		warehouse = d.get(warehouse_field)

		if has_batch_no and warehouse and not d.get("packing_slip") and not d.get("source_packing_slip"):
			batches = get_sufficient_batch_or_fifo(d.item_code, warehouse, flt(d.qty), flt(d.conversion_factor),
				batches_used=batches_used, include_empty_batch=True, precision=d.precision('qty'))

			rows = [d]

			for i in range(1, len(batches)):
				new_row = frappe.copy_doc(d)
				rows.append(new_row)
				updated_rows.append(new_row)

			for row, batch in zip(rows, batches):
				row.qty = batch.selected_qty
				row.batch_no = batch.batch_no

	# Replace with updated list
	for i, row in enumerate(updated_rows):
		row.idx = i + 1
	doc.items = updated_rows


@frappe.whitelist()
def get_batch_no(item_code, warehouse, qty=1, throw=False, sales_order_item=None, serial_no=None):
	"""
	Get batch number using First Expiring First Out method.
	:param item_code: `item_code` of Item Document
	:param warehouse: name of Warehouse to check
	:param qty: quantity of Items
	:return: String represent batch number of batch with sufficient quantity else an empty String
	"""

	batch_no = None
	batches = get_batches(item_code, warehouse, sales_order_item=sales_order_item)

	for batch in batches:
		if flt(qty) <= flt(batch.qty):
			batch_no = batch.name
			break

	if not batch_no:
		batch_no=""
		return batch_no

	return batch_no


@frappe.whitelist()
def get_sufficient_batch_or_fifo(item_code, warehouse, qty=1.0, conversion_factor=1.0, batches_used=None,
		include_empty_batch=False, precision=None, include_unselected_batches=False):
	if not warehouse or not qty:
		return []

	precision = cint(precision)
	if not precision:
		precision = cint(frappe.db.get_default("float_precision")) or 3

	batches = get_batches(item_code, warehouse)

	if isinstance(batches_used, str):
		batches_used = json.loads(batches_used or "{}")

	if batches_used:
		for batch in batches:
			if batch.name in batches_used:
				batch.qty -= flt(batches_used.get(batch.name))

		batches = [d for d in batches if d.qty > 0]

	selected_batches = []

	qty = flt(qty)
	conversion_factor = flt(conversion_factor or 1)
	stock_qty = qty * conversion_factor
	remaining_stock_qty = stock_qty

	for batch in batches:
		if remaining_stock_qty <= 0 and not cint(include_unselected_batches):
			break

		selected_stock_qty = min(remaining_stock_qty, batch.qty)
		selected_qty = round_down(selected_stock_qty / conversion_factor, precision)
		if not selected_qty and not cint(include_unselected_batches):
			continue

		selected_stock_qty = selected_qty * conversion_factor
		selected_batches.append(frappe._dict({
			'batch_no': batch.name,
			'available_qty': batch.qty / conversion_factor,
			'selected_qty': selected_qty
		}))

		if isinstance(batches_used, dict):
			batches_used.setdefault(batch.name, 0)
			batches_used[batch.name] += selected_stock_qty

		remaining_stock_qty -= selected_stock_qty

	if remaining_stock_qty > 0:
		if cint(include_empty_batch):
			selected_batches.append(frappe._dict({
				'batch_no': None,
				'available_qty': 0,
				'selected_qty': remaining_stock_qty / conversion_factor
			}))

		total_selected_qty = stock_qty - remaining_stock_qty
		frappe.msgprint(_("Only {0} {1} of {2} found in {3}").format(
			frappe.format(total_selected_qty, df={"fieldtype": "Float", "precision": 6}),
			frappe.get_cached_value("Item", item_code, "stock_uom"),
			frappe.get_desk_link('Item', item_code),
			frappe.get_desk_link('Warehouse', warehouse)
		))

	return selected_batches


def get_batch_received_date(batch_no, warehouse):
	date = frappe.db.sql("""
		select timestamp(posting_date, posting_time)
		from `tabStock Ledger Entry`
		where batch_no = %s and warehouse = %s
		order by posting_date, posting_time, creation
		limit 1
	""", [batch_no, warehouse])

	return date[0][0] if date else None


def get_batches(item_code, warehouse, posting_date=None, posting_time=None, qty_condition="positive", sales_order_item=None):
	if qty_condition == "both":
		having = "having qty != 0"
	elif qty_condition == "negative":
		having = "having qty < 0"
	else:
		having = "having qty > 0"

	date_cond = ""
	if posting_date:
		date_cond = "and (b.expiry_date is null or b.expiry_date >= %(posting_date)s)"
		if posting_time:
			date_cond += " and (sle.posting_date, sle.posting_time) <= (%(posting_date)s, %(posting_time)s)"
		else:
			date_cond += " and sle.posting_date <= %(posting_date)s"

	args = {
		'item_code': item_code,
		'warehouse': warehouse,
		'posting_date': posting_date,
		'posting_time': posting_time
	}

	batches = frappe.db.sql("""
		select b.name, sum(sle.actual_qty) as qty, b.expiry_date,
			min(timestamp(sle.posting_date, sle.posting_time)) received_date
		from `tabStock Ledger Entry` sle
		join `tabBatch` b on b.name = sle.batch_no
		where sle.item_code = %(item_code)s and sle.warehouse = %(warehouse)s
			and (sle.packing_slip = '' or sle.packing_slip is null)
			{0}
		group by b.name
		{1}
	""".format(date_cond, having), args, as_dict=True)

	batches = sorted(batches, key=lambda d: (d.expiry_date, d.received_date))

	if sales_order_item:
		batches_purchased_against_so = frappe.db.sql_list("""
			select pr_item.batch_no
			from `tabPurchase Receipt Item` pr_item
			inner join `tabPurchase Order Item` po_item on po_item.name = pr_item.purchase_order_item
			where pr_item.docstatus = 1 and po_item.sales_order_item = %s
		""", sales_order_item)

		available_preferred_batches = [batch for batch in batches if batch.name in batches_purchased_against_so]
		unpreferred_batches = [batch for batch in batches if batch.name not in batches_purchased_against_so]
		batches = available_preferred_batches + unpreferred_batches

	return batches


def validate_serial_no_with_batch(serial_nos, item_code):
	if frappe.get_cached_value("Serial No", serial_nos[0], "item_code") != item_code:
		frappe.throw(_("The serial no {0} does not belong to item {1}")
			.format(get_link_to_form("Serial No", serial_nos[0]), get_link_to_form("Item", item_code)))

	serial_no_link = ','.join([get_link_to_form("Serial No", sn) for sn in serial_nos])

	message = "Serial Nos" if len(serial_nos) > 1 else "Serial No"
	frappe.throw(_("There is no batch found against the {0}: {1}")
		.format(message, serial_no_link))
