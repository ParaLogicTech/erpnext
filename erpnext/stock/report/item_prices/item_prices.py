# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _, scrub
from frappe.utils import flt, nowdate, getdate, cstr, cint
from erpnext.stock.report.stock_ledger.stock_ledger import get_item_group_condition
from erpnext.stock.utils import has_valuation_read_permission
from erpnext.stock.doctype.item.item import convert_item_uom_for
from erpnext.setup.doctype.item_group.item_group import get_item_group_subtree
from erpnext.setup.doctype.customer_group.customer_group import get_customer_group_subtree
from crm.crm.doctype.territory.territory import get_territory_subtree
from frappe.model.meta import get_field_precision
from frappe.desk.reportview import build_match_conditions
import json


def execute(filters=None):
	# Get Data
	filters = process_filters(filters)
	item_prices_map, price_lists = get_item_price_data(filters)

	# Sort Data
	item_group_wise_data = {}
	for d in item_prices_map.values():
		item_group_wise_data.setdefault(d.item_group, []).append(d)

	price_list_settings = frappe.get_single("Price List Settings")
	rows = []

	for item_group in price_list_settings.item_group_order or []:
		if item_group.item_group in item_group_wise_data:
			rows += sorted(item_group_wise_data[item_group.item_group], key=lambda d: d.item_code)
			del item_group_wise_data[item_group.item_group]

	for items in item_group_wise_data.values():
		rows += sorted(items, key=lambda d: d.item_code)

	# Get Columns and Return
	columns = get_columns(filters, price_lists)
	return columns, rows


def process_filters(filters):
	filters = frappe._dict(filters or {})
	filters.date = getdate(filters.date or nowdate())

	if filters.buying_selling == "Selling":
		filters.standard_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
	elif filters.buying_selling == "Buying":
		filters.standard_price_list = frappe.db.get_single_value("Buying Settings", "buying_price_list")

	return filters


def get_item_price_data(filters, ignore_permissions=False, additional_conditions=None):
	price_lists, selected_price_list = get_price_lists(filters, ignore_permissions=ignore_permissions)

	item_data = get_items(filters, additional_conditions)
	item_price_data = get_current_item_prices(filters, price_lists, additional_conditions)
	previous_item_prices = get_previous_item_prices(filters, price_lists, additional_conditions)
	pricing_rule_map = get_pricing_rule_map(filters)
	bin_data = get_bin_data(filters, additional_conditions)
	po_data = get_po_data(filters)

	items_map = {}
	for d in item_data:
		d["disable_item_formatter"] = 1

		default_uom = d.purchase_uom if filters.buying_selling == "Buying" else d.sales_uom
		if filters.uom:
			d['uom'] = filters.uom
		elif filters.default_uom == "Stock UOM":
			d['uom'] = d.stock_uom
		elif filters.default_uom == "Contents UOM":
			d['uom'] = d.alt_uom or default_uom
		else:
			d['uom'] = default_uom

		if not d.get('uom'):
			d['uom'] = d.stock_uom

		d['print_in_price_list'] = cint(not d['hide_in_price_list'])
		del d['hide_in_price_list']

		d['alt_uom_size'] = convert_item_uom_for(d.alt_uom_size, d.item_code, d.uom, d.stock_uom)
		items_map[d.item_code] = d

	for d in po_data:
		if d.item_code in items_map:
			items_map[d.item_code].update(d)

	for d in bin_data:
		if d.item_code in items_map:
			items_map[d.item_code].update(d)

	for item_prices in [item_price_data, previous_item_prices]:
		for d in item_prices:
			if d.item_code in items_map:
				d.price_list_rate = convert_item_uom_for(d.price_list_rate, d.item_code,
					from_uom=d.uom or items_map[d.item_code]['stock_uom'], to_uom=items_map[d.item_code]['uom'],
					null_if_not_convertible=True, is_rate=True)

	item_price_map = {}
	for d in item_price_data:
		if d.item_code in items_map and d.price_list_rate is not None:
			current_item = items_map[d.item_code]
			price = item_price_map.setdefault(d.item_code, {}).setdefault(d.price_list, frappe._dict())
			pick_price = (cstr(d.uom) == cstr(current_item.uom)
					or (cstr(price.reference_uom) != cstr(current_item.uom) and cstr(d.uom) != current_item.stock_uom)
					or not price)

			if pick_price:
				price.current_price = d.price_list_rate
				price.valid_from = d.valid_from
				price.reference_uom = d.uom
				price.currency = d.currency

				if d.price_list == filters.standard_price_list:
					items_map[d.item_code].standard_rate = d.price_list_rate
					items_map[d.item_code].standard_rate_valid_from = d.valid_from

				show_amounts = has_valuation_read_permission()
				if show_amounts:
					price.item_price = d.name

	for d in previous_item_prices:
		if d.item_code in item_price_map and d.price_list in item_price_map[d.item_code] and d.price_list_rate is not None:
			price = item_price_map[d.item_code][d.price_list]
			if 'previous_price' not in price and d.valid_from < price.valid_from:
				price.previous_price = d.price_list_rate

	for item_code, d in items_map.items():
		d.actual_qty = convert_item_uom_for(flt(d.actual_qty), d.item_code, d.stock_uom, d.uom)
		d.po_qty = convert_item_uom_for(flt(d.po_qty), d.item_code, d.stock_uom, d.uom)

		d.po_lc_rate = flt(d.po_lc_amount) / d.po_qty if d.po_qty else 0
		d.valuation_rate = flt(d.stock_value) / d.actual_qty if d.actual_qty else 0

		d.balance_qty = d.actual_qty + d.po_qty
		d.avg_lc_rate = (flt(d.stock_value) + flt(d.po_lc_amount)) / d.balance_qty if d.balance_qty else 0
		d.margin_rate = (d.standard_rate - d.avg_lc_rate) * 100 / d.standard_rate if d.standard_rate else None

		for price_list, price in item_price_map.get(item_code, {}).items():
			d["rate_" + scrub(price_list)] = price.current_price
			d["currency_" + scrub(price_list)] = price.currency
			if d.standard_rate is not None:
				d["rate_diff_" + scrub(price_list)] = flt(price.current_price) - flt(d.standard_rate)
			if price.previous_price is not None:
				d["rate_old_" + scrub(price_list)] = price.previous_price
			if price.item_price:
				d["item_price_" + scrub(price_list)] = price.item_price
			if price.valid_from:
				d["valid_from_" + scrub(price_list)] = price.valid_from

		apply_pricing_rules(d, pricing_rule_map, price_lists)

		if filters.standard_price_list and filters.price_list_1:
			standard_rate = d.get("rate_" + scrub(filters.standard_price_list))
			comparison_rate = d.get("rate_" + scrub(filters.price_list_1))
			if standard_rate and comparison_rate:
				ratio_field = get_comparison_ratio_field(filters.standard_price_list, filters.price_list_1)
				d[ratio_field] = standard_rate / comparison_rate

		using_price_list = selected_price_list or filters.standard_price_list
		if using_price_list:
			d.price_list_rate = d.get("rate_" + scrub(using_price_list))
			d.rate_with_margin = d.get("pr_rate_with_margin" + scrub(using_price_list))
			d.discount_percentage = d.get("pr_discount_percentage_" + scrub(using_price_list))
			d.discount_amount = d.get("pr_discount_amount_" + scrub(using_price_list))
			d.pricing_rule_rate = d.get("pr_rate_" + scrub(using_price_list))
		else:
			d.price_list_rate = d.standard_rate
			d.rate_with_margin = None
			d.discount_percentage = None
			d.discount_amount = None
			d.pricing_rule_rate = None

		d.print_price_list_rate = d.rate_with_margin or d.price_list_rate
		if flt(d.pricing_rule_rate) and flt(d.pricing_rule_rate) > flt(d.print_price_list_rate):
			d.print_price_list_rate = flt(d.pricing_rule_rate)

		d.print_rate = d.pricing_rule_rate or d.print_price_list_rate

	if filters.filter_items_without_price:
		to_remove = []
		for item_code, d in items_map.items():
			if not d.get('print_rate'):
				to_remove.append(item_code)
		for item_code in to_remove:
			del items_map[item_code]

	return items_map, price_lists


def get_price_lists(filters, ignore_permissions=False):
	def get_additional_price_lists():
		res = []
		for i in range(1):
			if filters.get('price_list_' + str(i+1)):
				res.append(filters.get('price_list_' + str(i+1)))
		return res

	def add_to_price_lists(price_list):
		if not price_list:
			return

		if not isinstance(price_list, list):
			price_list = [price_list]

		for pl in price_list:
			if pl and pl not in price_lists:
				price_lists.append(pl)

	conditions = []

	if filters.filter_price_list_by == "Disabled":
		conditions.append("enabled = 0")
	elif filters.filter_price_list_by == "Enabled":
		conditions.append("enabled = 1")

	if filters.buying_selling == "Selling":
		conditions.append("selling = 1")
	elif filters.buying_selling == "Buying":
		conditions.append("buying = 1")

	match_conditions = None
	if not ignore_permissions:
		match_conditions = build_match_conditions("Price List")
	if match_conditions:
		conditions.append(match_conditions)

	conditions = "where " + " and ".join(conditions) if conditions else ""

	price_lists = []
	add_to_price_lists(filters.standard_price_list)

	if filters.customer:
		customer_price_list = frappe.db.get_value("Customer", filters.customer, 'default_price_list')
		if customer_price_list:
			filters.selected_price_list = customer_price_list

	add_to_price_lists(filters.selected_price_list)

	additional_price_lists = get_additional_price_lists()
	add_to_price_lists(additional_price_lists)

	if not additional_price_lists and not filters.selected_price_list:
		add_to_price_lists(frappe.db.sql_list("""
			select name
			from `tabPrice List`
			{0}
			order by creation
		""".format(conditions)))

	return price_lists, filters.selected_price_list


def get_items(filters, additional_conditions):
	item_conditions = get_item_conditions(filters, for_item_dt=True, additional_conditions=additional_conditions)

	return frappe.db.sql("""
		select item.name as item_code, item.item_name, item.item_group, item.brand,
			item.stock_uom, item.sales_uom, item.purchase_uom, item.alt_uom, item.alt_uom_size,
			item.hide_in_price_list
		from tabItem item
		where disabled != 1 {0}
	""".format(item_conditions), filters, as_dict=1)


def get_current_item_prices(filters, price_lists, additional_conditions):
	item_conditions = get_item_conditions(filters, for_item_dt=True, additional_conditions=additional_conditions)
	price_lists_cond = " and p.price_list in ({0})".format(", ".join([frappe.db.escape(d) for d in price_lists or ['']]))

	return frappe.db.sql("""
		select p.name, p.price_list, p.item_code, p.price_list_rate, p.currency, p.uom,
			ifnull(p.valid_from, '2000-01-01') as valid_from
		from `tabItem Price` p
		inner join `tabItem` item on item.name = p.item_code
		where
			(
				%(date)s between p.valid_from and p.valid_upto
				or (p.valid_upto is null and %(date)s >= p.valid_from)
				or (p.valid_from is null and %(date)s <= p.valid_upto)
				or (p.valid_from is null and p.valid_upto is null)
			)
			and ifnull(p.customer, '') = '' and ifnull(p.supplier, '') = ''
			{0} {1}
		order by p.uom
	""".format(item_conditions, price_lists_cond), filters, as_dict=1)


def get_previous_item_prices(filters, price_lists, additional_conditions):
	if filters.only_prices:
		return []

	item_conditions = get_item_conditions(filters, for_item_dt=True, additional_conditions=additional_conditions)
	price_lists_cond = " and p.price_list in ({0})".format(", ".join([frappe.db.escape(d) for d in price_lists or ['']]))

	return frappe.db.sql("""
		select p.price_list, p.item_code, p.price_list_rate, ifnull(p.valid_from, '2000-01-01') as valid_from, p.uom
		from `tabItem Price` as p
		inner join `tabItem` item on item.name = p.item_code
		where p.valid_upto is not null and p.valid_upto < %(date)s {0} {1}
		order by p.valid_upto desc
	""".format(item_conditions, price_lists_cond), filters, as_dict=1)


def get_pricing_rule_map(filters):
	pricing_rule_map = frappe._dict({
		"items": {},
		"item_groups": {},
		"brands": {},
	})

	if filters.get('customer'):
		customer_details = frappe.db.get_value("Customer", filters.customer,
			["customer_group", "territory"], as_dict=True) or frappe._dict()
	else:
		customer_details = frappe._dict()

	pricing_rule_data = frappe.db.sql("""
		select pr.name, pr.for_price_list, pr.priority,
			pr.apply_on, pr_item.item_code, pr_group.item_group, pr_brand.brand,
			pr.applicable_for, pr.customer, pr.customer_group, pr.territory,
			pr.margin_type, pr.margin_rate_or_amount,
			pr.rate_or_discount, pr.rate, pr.discount_percentage, pr.discount_amount
		from `tabPricing Rule` pr
		left join `tabPricing Rule Item Code` pr_item on pr_item.parent = pr.name
		left join `tabPricing Rule Item Group` pr_group on pr_group.parent = pr.name
		left join `tabPricing Rule Brand` pr_brand on pr_brand.parent = pr.name
		where
			pr.disable = 0
			and pr.selling = 1
			and pr.apply_on in ('Item Code', 'Item Group', 'Brand')
			and pr.price_or_product_discount = 'Price'
			and (
				%(date)s between pr.valid_from and pr.valid_upto
				or (pr.valid_upto is null and %(date)s >= pr.valid_from)
				or (pr.valid_from is null and %(date)s <= pr.valid_upto)
				or (pr.valid_from is null and pr.valid_upto is null)
			)
	""", filters, as_dict=1)

	for d in pricing_rule_data:
		if d.applicable_for == "Customer":
			if not filters.customer or filters.customer != d.customer:
				continue
		elif d.applicable_for == "Customer Group":
			customer_groups = get_customer_group_subtree(d.customer_group, cache=True)
			if not customer_details.customer_group or customer_details.customer_group not in customer_groups:
				continue
		elif d.applicable_for == "Territory":
			territories = get_territory_subtree(d.territory, cache=True)
			if not customer_details.territory or customer_details.territory not in territories:
				continue

		if d.apply_on == "Item Code":
			pricing_rule_map['items'].setdefault(d.item_code, {}).setdefault(cstr(d.for_price_list), []).append(d)
		elif d.apply_on == "Brand":
			pricing_rule_map['brands'].setdefault(d.brand, {}).setdefault(cstr(d.for_price_list), []).append(d)
		elif d.apply_on == "Item Group":
			item_groups = get_item_group_subtree(d.item_group, cache=True)
			for item_group in item_groups:
				pricing_rule_map['item_groups'].setdefault(item_group, {}).setdefault(cstr(d.for_price_list), []).append(d)

	for key, entity_dict in pricing_rule_map.items():
		for entity, price_list_dict in entity_dict.items():
			for price_list, pricing_rules in price_list_dict.items():
				pricing_rules.sort(key=lambda d: (
					d.priority,
					3 if d.applicable_for == 'Customer' else (2 if d.applicable_for == 'Customer Group' else (1 if d.applicable_for == 'Territory' else 0)),
					d.valid_from,
				), reverse=True)

	return pricing_rule_map


def apply_pricing_rules(row, pricing_rule_map, price_lists):
	pricing_rule_all_price_lists = pricing_rule_map['items'].get(row.item_code, {}).get('')
	if not pricing_rule_all_price_lists and row.item_group:
		pricing_rule_all_price_lists = pricing_rule_map['item_groups'].get(row.item_group, {}).get('')
	if not pricing_rule_all_price_lists and row.brand:
		pricing_rule_all_price_lists = pricing_rule_map['brands'].get(row.brand, {}).get('')

	if pricing_rule_all_price_lists:
		for price_list in price_lists:
			apply_pricing_rule_to_price_list(row, price_list, pricing_rule_all_price_lists[0])

	for price_list, pricing_rule in pricing_rule_map['brands'].get(row.brand, {}).items():
		if price_list and pricing_rule:
			apply_pricing_rule_to_price_list(row, price_list, pricing_rule[0])

	for price_list, pricing_rule in pricing_rule_map['item_groups'].get(row.item_group, {}).items():
		if price_list and pricing_rule:
			apply_pricing_rule_to_price_list(row, price_list, pricing_rule[0])

	for price_list, pricing_rule in pricing_rule_map['items'].get(row.item_code, {}).items():
		if price_list and pricing_rule:
			apply_pricing_rule_to_price_list(row, price_list, pricing_rule[0])


def apply_pricing_rule_to_price_list(row, price_list, pricing_rule):
	price_precision = get_field_precision(frappe.get_meta("Item Price").get_field('price_list_rate'))

	row['pricing_rule_' + scrub(price_list)] = pricing_rule.name

	price_list_rate = flt(row.get('rate_' + scrub(price_list)))

	if pricing_rule.margin_type == "Percentage":
		rate_with_margin = price_list_rate * (1 + flt(pricing_rule.margin_rate_or_amount) / 100)
	elif pricing_rule.margin_type == "Amount":
		rate_with_margin = price_list_rate + flt(pricing_rule.margin_rate_or_amount)
	else:
		rate_with_margin = price_list_rate

	discount_percentage = None

	if pricing_rule.rate_or_discount == "Rate":
		pricing_rule_rate = pricing_rule.rate
	elif pricing_rule.rate_or_discount == "Discount Percentage":
		discount_percentage = flt(pricing_rule.discount_percentage)
		pricing_rule_rate = rate_with_margin * (1 - discount_percentage / 100)
	elif pricing_rule.rate_or_discount == "Discount Amount":
		pricing_rule_rate = rate_with_margin - flt(pricing_rule.discount_amount)
	else:
		pricing_rule_rate = rate_with_margin

	rate_with_margin = flt(rate_with_margin, price_precision)
	row['pr_rate_with_margin' + scrub(price_list)] = rate_with_margin

	pricing_rule_rate = flt(max(0.0, flt(pricing_rule_rate)), price_precision)
	row['pr_rate_' + scrub(price_list)] = pricing_rule_rate

	if flt(discount_percentage) > 0:
		row['pr_discount_percentage_' + scrub(price_list)] = flt(discount_percentage)
	elif flt(pricing_rule_rate) and flt(pricing_rule_rate) < rate_with_margin:
		discount_amount = flt(rate_with_margin - pricing_rule_rate, price_precision)
		row['pr_discount_amount_' + scrub(price_list)] = discount_amount


def get_po_data(filters):
	if filters.only_prices:
		return []

	item_conditions = get_item_conditions(filters, for_item_dt=False)

	return frappe.db.sql("""
		select
			item.item_code,
			sum(if(item.qty - item.received_qty < 0, 0, item.qty - item.received_qty) * item.conversion_factor) as po_qty,
			sum(if(item.qty - item.received_qty < 0, 0, item.qty - item.received_qty) * item.conversion_factor * item.base_net_rate) as po_lc_amount
		from `tabPurchase Order Item` item
		inner join `tabPurchase Order` po on po.name = item.parent
		where item.docstatus = 1 and po.status != 'Closed' {0}
		group by item.item_code
	""".format(item_conditions), filters, as_dict=1)  # TODO add valuation rate in PO and use that


def get_bin_data(filters, additional_conditions):
	if filters.only_prices:
		return []

	item_conditions = get_item_conditions(filters, for_item_dt=True, additional_conditions=additional_conditions)

	return frappe.db.sql("""
		select
			bin.item_code,
			sum(bin.actual_qty) as actual_qty,
			sum(bin.stock_value) as stock_value
		from tabBin bin, tabItem item
		where item.name = bin.item_code {0}
		group by bin.item_code
	""".format(item_conditions), filters, as_dict=1)


def get_item_conditions(filters, for_item_dt, additional_conditions=None):
	conditions = []

	if filters.get("item_code"):
		is_template = frappe.db.get_value("Item", filters.get('item_code'), 'has_variants')
		item_variant_of_field = "variant_of" if for_item_dt else "item_code"
		item_code_field = "name" if for_item_dt else "item_code"

		if is_template:
			conditions.append("(item.{0} = %(item_code)s or item.{1} = %(item_code)s)".format(
				item_code_field, item_variant_of_field))
		else:
			conditions.append("item.{0} = %(item_code)s".format(item_code_field))
	else:
		if filters.get("brand"):
			conditions.append("item.brand=%(brand)s")
		if filters.get("item_group"):
			conditions.append(get_item_group_condition(filters.get("item_group")))

		if filters.get("customer_provided_items") and for_item_dt:
			if filters.get("customer_provided_items") == "Customer Provided Items Only":
				conditions.append("item.is_customer_provided_item = 1")
			elif filters.get("customer_provided_items") == "Exclude Customer Provided Items":
				conditions.append("item.is_customer_provided_item = 0")

	if filters.get("supplier") and for_item_dt:
		if frappe.get_meta("Item").has_field("default_supplier"):
			conditions.append("item.default_supplier = %(supplier)s")

	if additional_conditions:
		if isinstance(additional_conditions, list):
			conditions += additional_conditions
		else:
			conditions.append(additional_conditions)

	return " and " + " and ".join(conditions) if conditions else ""


def get_columns(filters, price_lists):
	show_item_name = frappe.defaults.get_global_default('item_naming_by') != "Item Name"

	columns = [
		{"fieldname": "item_code", "label": _("Item Code"), "fieldtype": "Link", "options": "Item",
			"width": 100 if show_item_name else 200,
			"price_list_note": frappe.db.get_single_value("Price List Settings", "price_list_note")
		},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 150},
		{"fieldname": "print_in_price_list", "label": _("Print"), "fieldtype": "Check", "width": 50, "editable": 1},
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Data", "width": 50},
		{"fieldname": "alt_uom_size", "label": _("Per Unit"), "fieldtype": "Float", "width": 68},
		# {"fieldname": "item_group", "label": _("Item Group"), "fieldtype": "Link", "options": "Item Group", "width": 120},
		{"fieldname": "po_qty", "label": _("PO Qty"), "fieldtype": "Float", "width": 80, "restricted": 1},
		{"fieldname": "po_lc_rate", "label": _("PO Rate"), "fieldtype": "Currency", "width": 90, "restricted": 1},
		{"fieldname": "actual_qty", "label": _("Stock Qty"), "fieldtype": "Float", "width": 80, "restricted": 1},
		{"fieldname": "valuation_rate", "label": _("Stock Rate"), "fieldtype": "Currency", "width": 90, "restricted": 1},
		{"fieldname": "avg_lc_rate", "label": _("Avg Rate"), "fieldtype": "Currency", "width": 90, "restricted": 1},
	]

	if filters.standard_price_list:
		if filters.show_valid_from:
			columns.append({
				"fieldname": "standard_rate_valid_from", "label": _("Valid From Std Rate"), "fieldtype": "Date", "width": 80
			})

		columns += [
			{"fieldname": "standard_rate", "label": filters.standard_price_list, "fieldtype": "Currency", "width": 110,
				"editable": 1, "price_list": filters.standard_price_list,
				"force_currency_symbol": 1, "options": "currency_" + scrub(filters.standard_price_list)},
			{"fieldname": "margin_rate", "label": _("Margin"), "fieldtype": "Percent", "width": 60, "restricted": 1},
		]

	for price_list in price_lists:
		if price_list != filters.standard_price_list:
			if filters.show_valid_from:
				columns.append({
					"fieldname": "valid_from_" + scrub(price_list), "label": _("Valid From {0}".format(price_list)), "fieldtype": "Date", "width": 80
				})

			columns.append({
				"fieldname": "rate_" + scrub(price_list),
				"label": price_list,
				"fieldtype": "Currency",
				"width": 110,
				"editable": 1,
				"price_list": price_list,
				"options": "currency_" + scrub(price_list),
				"force_currency_symbol": 1
			})

	if filters.standard_price_list and filters.price_list_1:
		columns.append({
			"fieldname": get_comparison_ratio_field(filters.standard_price_list, filters.price_list_1),
			"label": _("{0}/{1}").format(filters.standard_price_list, filters.price_list_1),
			"fieldtype": "Float",
			"width": 130,
		})

	show_amounts = has_valuation_read_permission()
	if not show_amounts:
		columns = list(filter(lambda d: not d.get('restricted'), columns))
		'''for c in columns:
			if c.get('editable'):
				del c['editable']'''

	if not show_item_name:
		columns = [c for c in columns if c.get('fieldname') != 'item_name']

	return columns


def get_comparison_ratio_field(numerator_price_list, divisor_price_list):
	return "ratio_" + scrub(numerator_price_list) + "_" + scrub(divisor_price_list)


@frappe.whitelist()
def set_multiple_item_pl_rate(effective_date, price_list, items):
	if isinstance(items, str):
		items = json.loads(items)

	for item in items:
		_set_item_pl_rate(effective_date, item.get('item_code'), price_list,
			item.get('price_list_rate'), item.get('uom'), item.get('conversion_factor'))


@frappe.whitelist()
def set_item_pl_rate(effective_date, item_code, price_list, price_list_rate, uom=None, conversion_factor=None, filters=None):
	effective_date = getdate(effective_date)
	_set_item_pl_rate(effective_date, item_code, price_list, price_list_rate, uom, conversion_factor)

	if filters is not None:
		if isinstance(filters, str):
			filters = json.loads(filters)

		filters['item_code'] = item_code
		return execute(filters)


def _set_item_pl_rate(effective_date, item_code, price_list, price_list_rate, uom=None, conversion_factor=None):
	from frappe.model.utils import get_fetch_values
	from erpnext.stock.get_item_details import get_item_price

	if not flt(price_list_rate):
		frappe.msgprint(_("Rate not set for Item {0} because rate is 0").format(item_code, price_list),
			alert=1, indicator="orange")
		return

	effective_date = getdate(effective_date)
	item_price_args = {
		"item_code": item_code,
		"price_list": price_list,
		"uom": uom,
		"min_qty": 0,
		"transaction_date": effective_date,
	}
	current_effective_item_price = get_item_price(item_price_args, item_code)

	existing_item_price = past_item_price = None
	if current_effective_item_price and getdate(current_effective_item_price.valid_from) == effective_date:
		existing_item_price = current_effective_item_price
	else:
		past_item_price = current_effective_item_price

	if current_effective_item_price:
		price_precision = get_field_precision(frappe.get_meta("Item Price").get_field('price_list_rate'))

		converted_rate = convert_item_uom_for(price_list_rate, item_code, uom, current_effective_item_price.uom,
			conversion_factor=conversion_factor, is_rate=True)
		if flt(converted_rate, price_precision) == flt(current_effective_item_price.price_list_rate, price_precision):
			frappe.msgprint(_("Rate not set for Item {0} because it is the same").format(item_code, price_list),
				alert=1, indicator="blue")
			return

	item_price_args['period'] = 'future'
	future_item_price = get_item_price(item_price_args, item_code)

	# Update or add item price
	if existing_item_price:
		doc = frappe.get_doc("Item Price", existing_item_price.name)
		converted_rate = convert_item_uom_for(price_list_rate, item_code, uom, doc.uom,
			conversion_factor=conversion_factor, is_rate=True)
		doc.price_list_rate = converted_rate
	else:
		doc = frappe.new_doc("Item Price")
		doc.item_code = item_code
		doc.price_list = price_list
		doc.uom = uom
		doc.price_list_rate = flt(price_list_rate)
		doc.update(get_fetch_values("Item Price", 'item_code', item_code))
		doc.update(get_fetch_values("Item Price", 'price_list', price_list))

	doc.valid_from = effective_date
	if future_item_price:
		doc.valid_upto = frappe.utils.add_days(future_item_price.valid_from, -1)
	doc.save()

	# Update previous item price
	before_effective_date = frappe.utils.add_days(effective_date, -1)
	if past_item_price and past_item_price.valid_upto != before_effective_date:
		frappe.set_value("Item Price", past_item_price.name, 'valid_upto', before_effective_date)

	frappe.msgprint(_("Price updated for Item {0} in Price List {1}").format(item_code, price_list),
		alert=1, indicator='green')
