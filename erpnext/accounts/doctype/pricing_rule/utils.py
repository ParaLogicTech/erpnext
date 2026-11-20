# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt, cstr, getdate, today
from erpnext.setup.doctype.item_group.item_group import get_item_group_subtree
from erpnext.stock.doctype.warehouse.warehouse import get_child_warehouses
from erpnext.stock.get_item_details import get_conversion_factor, determine_selling_or_buying
import json


class MultiplePricingRuleConflict(frappe.ValidationError): pass


apply_on_table = {
	'Item Code': 'items',
	'Brand': 'brands',
	'Item Group': 'item_groups',
}


def get_pricing_rules(args, doc=None):
	pricing_rules = []
	values = {}

	for apply_on in ['Item Code', 'Brand', 'Item Group']:
		pricing_rules.extend(_get_pricing_rules(apply_on, args, values))

	pricing_rules = filter_pricing_rules(pricing_rules, args, doc=doc)
	if not pricing_rules:
		return []

	applied_rules = []

	pricing_rules, apply_multiple = filter_pricing_rules_based_on_apply_multiple(pricing_rules)
	if apply_multiple:
		pricing_rules = sorted(pricing_rules, key=lambda d: cint(d.priority), reverse=True)
		for pricing_rule in pricing_rules:
			applied_rules.append(pricing_rule)
	else:
		pricing_rule = filter_highest_priority_pricing_rule(args, pricing_rules)
		if pricing_rule:
			applied_rules.append(pricing_rule)

	return applied_rules


def _get_pricing_rules(apply_on, args, values):
	apply_on_field = frappe.scrub(apply_on)
	if not args.get(apply_on_field):
		return []

	child_table = f"`tabPricing Rule {apply_on}`"

	item_conditions = []
	other_item_conditions = []

	values[apply_on_field] = args.get(apply_on_field)

	if apply_on_field in ["item_code", "brand"]:
		item_conditions.append(f"{child_table}.{apply_on_field} = %({apply_on_field})s")
		other_item_conditions.append(f"`tabPricing Rule`.other_{apply_on_field} = %({apply_on_field})s")

		if apply_on_field == "item_code" and args.variant_of:
			item_conditions.append(f"{child_table}.item_code = %(variant_of)s")
			other_item_conditions.append(f"`tabPricing Rule`.other_item_code = %(variant_of)s")
			values['variant_of'] = args.variant_of

	elif apply_on_field == "item_group":
		item_conditions.append(_get_tree_conditions(
			"Item Group",
			value=args.get("item_group"),
			table=child_table,
			allow_blank=False,
		))

		other_item_conditions.append(_get_tree_conditions(
			"Item Group",
			value=args.get("item_group"),
			field="other_item_group",
			allow_blank=False,
		))

	item_conditions = " or ".join(item_conditions)
	other_item_conditions = " or ".join(other_item_conditions)

	parent_doc_conditions = get_parent_doc_conditions(values, args)
	parent_doc_conditions.append("ifnull(`tabPricing Rule`.for_price_list, '') in (%(price_list)s, '')")
	values["price_list"] = args.get("price_list")

	parent_doc_conditions = " and ".join(parent_doc_conditions)
	if parent_doc_conditions:
		parent_doc_conditions = f" and {parent_doc_conditions}"

	warehouse_conditions = _get_tree_conditions("Warehouse", value=args.get("warehouse"))
	if warehouse_conditions:
		warehouse_conditions = f" and {warehouse_conditions}"

	pricing_rules = frappe.db.sql(f"""
		select `tabPricing Rule`.*, {child_table}.{apply_on_field}, {child_table}.uom
		from `tabPricing Rule`
		left join {child_table} on {child_table}.parent = `tabPricing Rule`.name
		where
			(
				({item_conditions})
				or (({other_item_conditions}) and ifnull(`tabPricing Rule`.apply_rule_on_other, '') != '')
			)
			and `tabPricing Rule`.disable = 0
			and `tabPricing Rule`.{args.selling_or_buying} = 1
			{parent_doc_conditions}
			{warehouse_conditions}
		order by `tabPricing Rule`.priority desc, `tabPricing Rule`.name desc
	""", values, as_dict=1) or []

	return pricing_rules


def filter_pricing_rules(pricing_rules, args, doc=None):
	filtered = []

	for rule in pricing_rules:
		if not validate_pricing_rule_validity(rule, args, doc=doc, keep_apply_on_other=True):
			continue
		if not validate_pricing_rule_based_on_item_price_availability(rule, args):
			continue

		filtered.append(rule)

	return filtered


def validate_pricing_rule_validity(rule, args, doc=None, keep_apply_on_other=False):
	# Free item of a Product Discount rule (except mix and match) is validated through its main item
	if args.get("is_free_item") and rule.price_or_product_discount == "Product" and not rule.mix_and_match:
		return True

	if (
		not check_is_other_item(args, rule)
		and not args.get("is_free_item")
		and not evaluate_pricing_rule_condition(rule, args, doc=doc)
	):
		return False

	if not validate_pricing_rule_based_on_coupon_code(rule, args):
		return False
	if not validate_pricing_rule_based_on_other_item(rule, args, doc=doc, keep_apply_on_other=keep_apply_on_other):
		return False
	if not validate_pricing_rule_based_on_qty_amount(rule, args, doc=doc, keep_apply_on_other=keep_apply_on_other):
		return False

	return True


def evaluate_pricing_rule_condition(rule, args, doc=None):
	from frappe.utils.safe_exec import get_safe_globals

	if not cstr(rule.get("condition")).strip():
		return True

	eval_globals = get_safe_globals()
	context = frappe._dict({
		"item_code": args.get("item_code"),
		"args": args,
		"doc": doc or frappe._dict(),
		"rule": rule,
	})

	try:
		if frappe.safe_eval(rule.condition, eval_globals, context):
			return True
		else:
			return False
	except Exception:
		return False


def validate_pricing_rule_based_on_coupon_code(rule, args):
	if not rule.coupon_code_based:
		return True

	if not args.coupon_code:
		return False

	coupon_pricing_rule = frappe.db.get_value("Coupon Code", args.coupon_code, "pricing_rule", cache=1)
	if rule.name != coupon_pricing_rule:
		return False

	return True


def validate_pricing_rule_based_on_other_item(rule, args, doc=None, keep_apply_on_other=False):
	if not rule.apply_rule_on_other:
		return True

	pr_doc = frappe.get_cached_doc("Pricing Rule", rule.name)

	other_item_apply_on_data = get_pricing_rule_apply_on_data(pr_doc, other_items=True)
	apply_on_other_field = frappe.scrub(pr_doc.get("apply_rule_on_other"))
	is_other_item = args.get(apply_on_other_field) in other_item_apply_on_data

	main_item_apply_on_data = get_pricing_rule_apply_on_data(pr_doc, other_items=False)
	apply_on_main_field = frappe.scrub(pr_doc.get("apply_on"))
	is_main_item = args.get(apply_on_main_field) in main_item_apply_on_data

	has_main_item = False
	if is_main_item:
		has_main_item = True
	elif is_other_item:
		main_rows = get_rows_based_on_apply_on(
			doc,
			rule,
			main_item_apply_on_data,
			apply_on_main_field,
			args,
			eval_condition=True,
		)
		if any(row.get("qty") for row in main_rows):
			has_main_item = True

	if is_main_item:
		rule.apply_rule_on_other_items = other_item_apply_on_data

	if is_other_item and has_main_item:
		return True
	if is_main_item and keep_apply_on_other:
		return True

	return False


def check_is_other_item(args, pr_doc):
	other_item_apply_on_data = get_pricing_rule_apply_on_data(pr_doc, other_items=True)
	apply_on_other_field = frappe.scrub(pr_doc.get("apply_rule_on_other"))
	return args.get(apply_on_other_field) in other_item_apply_on_data


def validate_pricing_rule_based_on_qty_amount(rule, args, doc=None, keep_apply_on_other=False):
	stock_qty = flt(args.get('stock_qty'))
	amount = flt(args.get('price_list_rate')) * flt(args.get('qty'))

	pr_doc = frappe.get_cached_doc('Pricing Rule', rule.name)
	main_item_code = None

	if rule.mixed_conditions:
		stock_qty, amount, items = get_qty_amount_for_mixed_conditions(doc, pr_doc, args)
		rule.apply_rule_on_other_items = items
		if keep_apply_on_other:
			return True

	elif rule.apply_rule_on_other:
		stock_qty, amount, main_item_code, is_main_item = get_qty_amount_for_other_item(doc, rule, pr_doc, args)
		if keep_apply_on_other and is_main_item:
			return True

	elif rule.is_cumulative:
		items = [args.get(frappe.scrub(pr_doc.get('apply_on')))]
		cum_qty, cum_amt = get_qty_amount_data_for_cumulative(pr_doc, args, items)
		stock_qty += cum_qty
		amount += cum_amt

	if not validate_pricing_rule_qty_amount(stock_qty, amount, rule, item_code=args.get('item_code')):
		if rule.threshold_percentage:
			get_qty_amount_suggestion(
				rule,
				stock_qty,
				amount,
				item_code=main_item_code or args.get('item_code'),
				selling_or_buying=args.get('selling_or_buying'),
			)

		return False

	return True


def validate_pricing_rule_qty_amount(stock_qty, amount, rule, item_code=None):
	stock_qty = flt(stock_qty, 6)
	amount = flt(amount, 6)
	item_code = item_code or rule.get("item_code")

	conversion_factor = 1
	if item_code and rule.get("uom"):
		conversion_factor = flt(get_conversion_factor(item_code, rule.uom).get("conversion_factor") or 1)

	min_qty = flt(flt(rule.min_qty) * conversion_factor, 6)
	max_qty = flt(flt(rule.max_qty) * conversion_factor, 6)
	min_amt = flt(rule.min_amt)
	max_amt = flt(rule.max_amt)

	if rule.price_or_product_discount == "Product":
		if not stock_qty:
			return False

		if rule.buy_qty:
			buy_qty = flt(rule.buy_qty)
			# mix and match qty includes free qty, so buy qty and free qty are both required
			if rule.mixed_conditions and rule.mix_and_match:
				buy_qty += flt(rule.free_qty)

			min_qty = max(min_qty, buy_qty)

	if stock_qty < min_qty or (max_qty and stock_qty > max_qty):
		return False
	if amount < min_amt or (max_amt and amount > max_amt):
		return False

	return True


def get_qty_amount_suggestion(rule, qty, amount, item_code, selling_or_buying):
	fieldname = ''
	msg = ''
	type_of_transaction = 'buy' if selling_or_buying == 'buying' else 'sell'

	min_field_map = {'min_qty': qty, 'min_amt': amount}
	for field, value in min_field_map.items():
		if (
			rule.get(field)
			and value < rule.get(field)
			and rule.get(field) - cint(rule.get(field) * rule.threshold_percentage * 0.01) <= value
		):
			fieldname = field

	max_field_map = {'max_qty': qty, 'max_amt': amount}
	for field, value in max_field_map.items():
		if (
			rule.get(field)
			and value > rule.get(field)
			and (rule.get(field) + cint(rule.get(field) * rule.threshold_percentage * 0.01)) >= value
		):
			fieldname = field

	if fieldname:
		msg = _("If you {0} {1} quantities of the item {2}, the scheme {3} will be applied on the item.").format(
			type_of_transaction,
			frappe.format(rule.get(fieldname)),
			frappe.bold(item_code),
			frappe.bold(rule.rule_description),
		)

		if fieldname in ['min_amt', 'max_amt']:
			msg = _("If you {0} {1} worth of item {2}, the scheme {3} will be applied on the item.").format(
				type_of_transaction,
				frappe.utils.fmt_money(rule.get(fieldname), currency=rule.currency),
				frappe.bold(item_code),
				frappe.bold(rule.rule_description)
			)

		frappe.msgprint(msg, alert=True)

	return frappe._dict({'suggestion': msg, 'item_code': item_code})


def validate_pricing_rule_based_on_item_price_availability(rule, args):
	from erpnext.stock.get_item_details import get_price_list_rate_for

	if not rule.get('ignore_if_item_price_available'):
		return True

	price_list = rule.for_price_list or args.get('price_list')

	item_price_args = {
		"item_code": args.get("item_code"),
		"price_list": price_list,
		"transaction_date": args.get("transaction_date") or today(),
		"uom": args.get("uom")
	}

	item_price_data = get_price_list_rate_for(args.get("item_code"), price_list, item_price_args)
	if item_price_data:
		return False

	return True


def filter_pricing_rules_based_on_apply_multiple(pricing_rules):
	apply_multiple = 0
	highest_priority = max([cint(d.priority) for d in pricing_rules])
	highest_priority_pricing_rules = [d for d in pricing_rules if cint(d.priority) == highest_priority]
	if all(d.apply_multiple_pricing_rules for d in highest_priority_pricing_rules):
		apply_multiple = 1

	if apply_multiple:
		pricing_rules = [d for d in pricing_rules if d.apply_multiple_pricing_rules]

	return pricing_rules, apply_multiple


def get_parent_doc_conditions(values, args):
	conditions = []

	for field in ["company", "customer", "supplier", "campaign", "sales_partner", "applies_to_item_brand"]:
		if args.get(field):
			conditions.append(f"ifnull(`tabPricing Rule`.{field}, '') in (%({field})s, '')")
			values[field] = args.get(field)
		else:
			conditions.append(f"ifnull(`tabPricing Rule`.{field}, '') = ''")

	for tree_doctype in ["Customer Group", "Territory", "Supplier Group"]:
		group_condition = _get_tree_conditions(tree_doctype, value=args.get(frappe.scrub(tree_doctype)))
		if group_condition:
			conditions.append(group_condition)

	if args.get("applies_to_item"):
		values['applies_to_item'] = args.get('applies_to_item')

		if args.get("applies_to_variant_of"):
			conditions.append("ifnull(`tabPricing Rule`.applies_to_item, '') in (%(applies_to_item)s, %(applies_to_variant_of)s, '')")
			values['applies_to_variant_of'] = args.get('applies_to_variant_of')
		else:
			conditions.append("ifnull(`tabPricing Rule`.applies_to_item, '') in (%(applies_to_item)s, '')")
	else:
		conditions.append("ifnull(`tabPricing Rule`.applies_to_item, '') = ''")

	applies_to_item_group_condition = _get_tree_conditions(
		"Item Group",
		value=args.get("applies_to_item_group"),
		field="applies_to_item_group",
	)
	if applies_to_item_group_condition:
		conditions.append(applies_to_item_group_condition)

	if args.get("transaction_date"):
		conditions.append("%(transaction_date)s between ifnull(`tabPricing Rule`.valid_from, '2000-01-01') and ifnull(`tabPricing Rule`.valid_upto, '2500-12-31')")
		values['transaction_date'] = args.get('transaction_date')

	if args.get("ignore_pricing_rule"):
		conditions.append("`tabPricing Rule`.prevent_ignore_pricing_rule = 1")

	frappe.utils.call_hook_method("update_pricing_rule_parent_doc_conditions", conditions, values, args)

	return conditions


def _get_tree_conditions(tree_doctype, value, field=None, table="`tabPricing Rule`", allow_blank=True):
	field = field or frappe.scrub(tree_doctype)

	parent_groups = _get_tree_parent_groups(tree_doctype, value)

	if parent_groups:
		if allow_blank:
			parent_groups.append('')

		parent_groups_str = ", ".join([frappe.db.escape(d) for d in parent_groups])
		condition = f"ifnull({table}.{field}, '') in ({parent_groups_str})"
	else:
		if allow_blank:
			condition = f"ifnull({table}.{field}, '') = ''"
		else:
			condition = f"{table}.{field} = ''"

	return condition


def _get_tree_parent_groups(tree_doctype, value):
	def generator():
		parent_groups = []
		if value:
			lft_rgt = frappe.db.get_value(tree_doctype, value, ["lft", "rgt"])
			if not lft_rgt:
				frappe.throw(_("Invalid {0} {1}").format(tree_doctype, frappe.bold(value)))

			lft, rgt = lft_rgt
			parent_groups = frappe.db.sql_list(f"""
				select name
				from `tab{tree_doctype}`
				where lft <= {lft} and rgt >= {rgt}
			""")

		return parent_groups

	key = (tree_doctype, cstr(value))
	out = frappe.local_cache("pricing_rule_get_tree_parent_groups", key, generator)
	return out.copy()


def filter_highest_priority_pricing_rule(args, pricing_rules):
	# find pricing rule with highest priority
	if pricing_rules:
		max_priority = max([cint(p.priority) for p in pricing_rules])
		if max_priority:
			pricing_rules = list(filter(lambda x: cint(x.priority) == max_priority, pricing_rules))

	# apply internal priority
	all_fields = [
		"item_code", "variant_of", "brand", "item_group",
		"customer", "customer_group", "territory",
		"supplier", "supplier_group",
		"campaign", "sales_partner",
		"applies_to_item", "applies_to_item_group", "applies_to_item_brand",
	]

	if len(pricing_rules) > 1:
		for field_set in [
			["item_code", "variant_of", "brand", "item_group"],
			["customer", "customer_group", "territory"],
			["supplier", "supplier_group"],
			["applies_to_item", "applies_to_item_brand", "applies_to_item_group"],
		]:
			remaining_fields = list(set(all_fields) - set(field_set))
			if if_all_rules_same(pricing_rules, remaining_fields):
				pricing_rules = apply_internal_priority(pricing_rules, field_set, args)
				break

	if pricing_rules and not isinstance(pricing_rules, list):
		pricing_rules = list(pricing_rules)

	if len(pricing_rules) > 1:
		rate_or_discount = list(set([d.rate_or_discount for d in pricing_rules]))
		if len(rate_or_discount) == 1 and rate_or_discount[0] == "Discount Percentage":
			pricing_rules = list(filter(lambda x: x.for_price_list == args.price_list, pricing_rules)) or pricing_rules

	if len(pricing_rules) > 1 and not args.for_shopping_cart:
		frappe.throw(_("Multiple Price Rules exists with same criteria, please resolve conflict by assigning priority. Pricing Rules:<ol>{0}</ol>").format(
			"".join([f"<li>{frappe.utils.get_link_to_form('Pricing Rule', d.name)}</li>" for d in pricing_rules])
		), MultiplePricingRuleConflict)
	elif pricing_rules:
		return pricing_rules[0]


def if_all_rules_same(pricing_rules, fields):
	all_rules_same = True
	val = [pricing_rules[0].get(k) for k in fields]
	for p in pricing_rules[1:]:
		if val != [p.get(k) for k in fields]:
			all_rules_same = False
			break

	return all_rules_same


def apply_internal_priority(pricing_rules, field_set, args):
	filtered_rules = []
	for field in field_set:
		if args.get(field):
			# filter function always returns a filter object even if empty
			# list conversion is necessary to check for an empty result
			filtered_rules = list(filter(lambda x: x.get(field)==args.get(field), pricing_rules))
			if filtered_rules:
				break

	return filtered_rules or pricing_rules


def get_qty_amount_for_mixed_conditions(doc, pr_doc, args):
	apply_on_data = get_pricing_rule_apply_on_data(pr_doc) or []
	apply_on_field = frappe.scrub(pr_doc.get("apply_on"))

	sum_qty = 0
	sum_amt = 0

	rows = get_rows_based_on_apply_on(
		doc,
		pr_doc,
		apply_on_data,
		apply_on_field,
		args,
		eval_condition=True,
	)

	for row in rows:
		row_data = args if args.get("child_docname") == row.name else row

		stock_qty = flt(row_data.get("qty")) * flt(row_data.get("conversion_factor"))
		amount = flt(row_data.get("qty")) * flt(row_data.get("price_list_rate"))

		sum_qty += stock_qty
		sum_amt += amount

	if pr_doc.is_cumulative:
		cum_qty, cum_amt = get_qty_amount_data_for_cumulative(pr_doc, doc, apply_on_data)
		if cum_qty:
			sum_qty += cum_qty
			sum_amt += cum_amt

	return sum_qty, sum_amt, apply_on_data


def get_qty_amount_for_other_item(doc, rule, pr_doc, args):
	main_item_apply_on_data = get_pricing_rule_apply_on_data(pr_doc, other_items=False)
	apply_on_main_field = frappe.scrub(pr_doc.get("apply_on"))
	is_main_item = args.get(apply_on_main_field) in main_item_apply_on_data

	max_stock_qty = 0
	max_amount = 0
	main_item_code = None

	main_rows = get_rows_based_on_apply_on(
		doc,
		pr_doc,
		main_item_apply_on_data,
		apply_on_main_field,
		args,
		eval_condition=True,
	)

	for row in main_rows:
		if not row.get("qty"):
			continue

		row_data = args if args.get("child_docname") == row.name else row

		stock_qty = flt(row_data.get("qty")) * flt(row_data.get("conversion_factor"))
		amount = flt(row_data.get("qty")) * flt(row_data.get("price_list_rate"))

		if validate_pricing_rule_qty_amount(stock_qty, amount, rule, item_code=row.item_code):
			return stock_qty, amount, row.item_code, is_main_item

		if stock_qty > max_stock_qty or amount > max_amount:
			max_stock_qty = stock_qty
			max_amount = amount
			main_item_code = row.item_code

	return max_stock_qty, max_amount, main_item_code, is_main_item


def get_rows_based_on_apply_on(doc, pricing_rule, apply_on_data, apply_on_field, args, eval_condition=False):
	rows = []
	if apply_on_data and doc and doc.get("items"):
		parent_dict = doc.get_item_details_parent_args()
		for row in doc.get("items"):
			row_args = get_args_for_other_item(doc, row, args, parent_dict=parent_dict)

			if row_args.get(apply_on_field) not in apply_on_data:
				continue

			if row.get("is_free_item") and not pricing_rule.mix_and_match:
				continue

			if eval_condition:
				if not evaluate_pricing_rule_condition(pricing_rule, row_args, doc=doc):
					continue

			rows.append(row)

	return rows


def get_args_for_other_item(doc, row, args, parent_dict=None):
	if args.get("child_docname") == row.name:
		return args
	elif doc:
		from erpnext.accounts.doctype.pricing_rule.pricing_rule import update_args_for_pricing_rule

		if not parent_dict:
			parent_dict = doc.get_item_details_parent_args()

		row_args = doc.get_item_details_child_args(row, parent_dict)
		row_args.selling_or_buying = args.get("selling_or_buying")
		update_args_for_pricing_rule(row_args)
		return row_args
	else:
		return frappe._dict()


def get_qty_amount_data_for_cumulative(pr_doc, doc, apply_on_data=None):
	doctype = doc.get("parenttype") or doc.doctype

	date_field = "transaction_date" if frappe.get_meta(doctype).has_field('transaction_date') else "posting_date"

	child_doctype = f"{doctype} Item"
	apply_on_field = frappe.scrub(pr_doc.get('apply_on'))

	values = [pr_doc.valid_from, pr_doc.valid_upto]
	condition = ""

	if pr_doc.warehouse:
		warehouses = get_child_warehouses(pr_doc.warehouse)
		condition += f""" and `tab{child_doctype}`.warehouse in ({','.join(['%s'] * len(warehouses))})"""
		values.extend(warehouses)

	if apply_on_data:
		condition = f" and `tab{child_doctype}`.{apply_on_field} in ({','.join(['%s'] * len(apply_on_data))})"
		values.extend(apply_on_data)

	data_set = frappe.db.sql(f"""
		SELECT `tab{child_doctype}`.stock_qty, `tab{child_doctype}`.amount
		FROM `tab{child_doctype}`, `tab{doctype}`
		WHERE
			`tab{child_doctype}`.parent = `tab{doctype}`.name
			and `tab{doctype}`.{date_field} between %s and %s
			and `tab{doctype}`.docstatus = 1
			{condition}
		GROUP BY `tab{child_doctype}`.name
	""", tuple(values), as_dict=1)

	cum_qty = 0
	cum_amt = 0
	for data in data_set:
		cum_qty += data.get('stock_qty')
		cum_amt += data.get('amount')

	return cum_qty, cum_amt


def apply_pricing_rule_on_transaction(doc):
	values = {}
	conditions = get_parent_doc_conditions(values, doc)
	conditions.append("apply_on = 'Transaction'")

	args = frappe._dict({
		'doctype': doc.doctype,
		'selling_or_buying': None,
	})

	determine_selling_or_buying(args)
	tran_type_condition = '{} = 1'.format(args.selling_or_buying)

	conditions = " and ".join(conditions)

	sql = """
		SELECT
			`tabPricing Rule`.*
		FROM
			`tabPricing Rule`
		WHERE
			{conditions} and
			{tran_type_condition} and
			`tabPricing Rule`.disable = 0
	""".format(
		conditions=conditions,
		tran_type_condition=tran_type_condition,
	)

	pricing_rules = frappe.db.sql(sql, values, as_dict=1)

	if pricing_rules:
		for rule in pricing_rules:
			if not validate_pricing_rule_qty_amount(doc.total_qty, doc.total, rule):
				continue

			if rule.price_or_product_discount == 'Price':
				if rule.apply_discount_on:
					doc.set('apply_discount_on', rule.apply_discount_on)

				for field in ['additional_discount_percentage', 'discount_amount']:
					pr_field = 'discount_percentage' if field == 'additional_discount_percentage' else field
					if not rule.get(pr_field):
						continue

					if rule.validate_applied_rule and doc.get(field) < rule.get(pr_field):
						frappe.msgprint(_("User has not applied rule on the invoice {0}").format(
							doc.name
						))
					else:
						doc.set(field, rule.get(pr_field))

				doc.calculate_taxes_and_totals()

			elif rule.price_or_product_discount == 'Product' and not rule.mix_and_match:
				item_details = frappe._dict({'parenttype': doc.doctype})
				free_item_data = get_product_discount_rule(rule, item_details, doc=doc, for_validate=True)
				apply_free_item_pricing_rule(doc, free_item_data, set_missing_values=True)
				doc.calculate_taxes_and_totals()


def update_pricing_rule_table(doc):
	if not doc.meta.has_field('pricing_rules'):
		return

	actual_pricing_rules = set()

	for d in doc.items:
		item_pricing_rules = get_applied_pricing_rules(d.get('pricing_rules'))
		for pricing_rule in item_pricing_rules:
			actual_pricing_rules.add((cstr(d.item_code), pricing_rule))

	to_remove = []
	for d in doc.pricing_rules:
		if (cstr(d.item_code), d.pricing_rule) not in actual_pricing_rules:
			to_remove.append(d)
	for d in to_remove:
		doc.remove(d)

	if to_remove:
		for i, d in enumerate(doc.pricing_rules):
			d.idx = i + 1

	existing_pricing_rules = set()
	for d in doc.pricing_rules:
		existing_pricing_rules.add((cstr(d.item_code), d.pricing_rule))

	to_add = actual_pricing_rules - existing_pricing_rules
	for item_code, pricing_rule in to_add:
		doc.append('pricing_rules', {
			'item_code': item_code,
			'pricing_rule': pricing_rule,
			'rule_applied': 1
		})


def get_applied_pricing_rules(pricing_rules):
	if pricing_rules:
		if pricing_rules.startswith('['):
			return json.loads(pricing_rules)
		else:
			return [pricing_rules]

	return []


def get_pricing_rules_str(pricing_rules):
	if not pricing_rules:
		return ""
	elif isinstance(pricing_rules, str):
		return pricing_rules
	elif len(pricing_rules) == 1:
		return pricing_rules[0]
	else:
		return json.dumps(pricing_rules, separators=(',', ':'), indent=0)


def get_product_discount_rule(
	pricing_rule,
	main_item_details,
	main_item_args=None,
	doc=None,
	for_validate=False,
):
	main_item_args = frappe._dict(main_item_args or {})

	free_item = pricing_rule.free_item
	if pricing_rule.same_item:
		free_item = main_item_details.item_code or main_item_args.item_code

	if not free_item:
		return None

	free_qty, free_item_uom = calculate_free_qty_and_uom(pricing_rule, main_item_args, doc)

	free_item_data = get_free_item_data(
		pricing_rule,
		free_item,
		free_qty,
		free_item_uom or None,
		main_item_args=main_item_args,
		doc=doc,
		for_validate=for_validate,
	)

	if pricing_rule.get("apply_rule_on_other_items"):
		free_item_data.update({
			'apply_rule_on_other_items': json.dumps(pricing_rule.apply_rule_on_other_items or []),
			'apply_rule_on': frappe.scrub(pricing_rule.get('apply_on'))
		})

	return free_item_data


def calculate_free_qty_and_uom(pricing_rule, main_item_args, doc, rows=None):
	qty = flt(main_item_args.qty)
	stock_qty = flt(main_item_args.stock_qty)

	if rows:
		stock_qty = flt(sum([flt(d.stock_qty) for d in rows]), 6)
	elif pricing_rule.mixed_conditions:
		pr_doc = frappe.get_cached_doc('Pricing Rule', pricing_rule.name)
		stock_qty, amount, items = get_qty_amount_for_mixed_conditions(doc, pr_doc, main_item_args)

	# mix and match needs to calculate from total qty that includes free qty, calculate paid qty first
	# non recursive free qty is fixed, minimum qty is validated in validate_pricing_rule_qty_amount
	if pricing_rule.mixed_conditions and pricing_rule.mix_and_match:
		if pricing_rule.free_qty:
			if pricing_rule.buy_qty and pricing_rule.free_qty_recursive:
				stock_qty = stock_qty * flt(pricing_rule.buy_qty) / (flt(pricing_rule.free_qty) + flt(pricing_rule.buy_qty))
			elif pricing_rule.free_qty_recursive:
				stock_qty /= 2
			else:
				stock_qty -= flt(pricing_rule.free_qty)
		else:
			stock_qty /= 2

	# calculate actual free qty
	if pricing_rule.free_qty:
		if pricing_rule.buy_qty and pricing_rule.free_qty_recursive:
			multiples = cint(stock_qty / flt(pricing_rule.buy_qty))
			free_qty = flt(pricing_rule.free_qty) * multiples
		elif pricing_rule.free_qty_recursive:
			free_qty = stock_qty if pricing_rule.mixed_conditions else qty
		else:
			free_qty = flt(pricing_rule.free_qty)
	else:
		free_qty = stock_qty if pricing_rule.mixed_conditions else qty

	free_item_uom = pricing_rule.free_item_uom
	if not free_item_uom and pricing_rule.same_item:
		free_item_uom = main_item_args.uom

	return free_qty, free_item_uom or None


def get_free_item_data(
	pricing_rule,
	free_item,
	free_qty,
	free_item_uom,
	main_item_args=None,
	doc=None,
	for_validate=False,
):
	free_item_data = frappe._dict({
		"item_code": free_item,
		"qty": free_qty,
		"uom": free_item_uom or None,
		"rate": flt(pricing_rule.free_item_rate),
		"discount_percentage": 100,
		"discount_amount": 0,
		"is_free_item": 1,
		"pricing_rules": pricing_rule.name,
	})

	if not for_validate and main_item_args:
		from erpnext.stock.get_item_details import get_item_details

		free_item_args = main_item_args.copy()
		free_item_args.update(free_item_data)
		free_item_args.doctype = free_item_args.get("parenttype") or free_item_args.get("doctype")
		free_item_args.name = free_item_args.get("parent") or free_item_args.get("name")
		free_item_args.pop("child_docname", None)

		free_item_details = get_item_details(free_item_args, doc=doc)
		for k, v in free_item_data.items():
			if v is not None:
				free_item_details[k] = v

		free_item_data = free_item_details

	set_free_item_rate_and_discount(free_item_data, pricing_rule.free_item_rate)

	return free_item_data


def set_free_item_rate_and_discount(row, free_item_rate):
	free_item_rate = flt(free_item_rate)
	rate_before_discount = flt(row.get("rate_with_margin")) or flt(row.get("price_list_rate"))

	row.rate = free_item_rate
	if not free_item_rate:
		row.discount_percentage = 100
		row.discount_amount = 0
	elif rate_before_discount:
		row.discount_amount = max(rate_before_discount - free_item_rate, 0)
		row.discount_percentage = row.discount_amount / rate_before_discount * 100
	else:
		row.discount_percentage = 0
		row.discount_amount = 0


def apply_free_item_pricing_rule(
	doc,
	free_item_data,
	set_missing_values=False,
	for_validate=False,
	row=None,
):
	if not free_item_data.get("item_code"):
		return

	update_fields = [
		"qty",
		"rate",
		"discount_percentage",
		"discount_amount",
	]

	free_rows = [d for d in doc.items if (
		d.item_code == free_item_data.get("item_code")
		and d.pricing_rules == free_item_data.get("pricing_rules")
		and d.is_free_item
		and (not row or d != row)
	)]
	to_remove = []

	if free_rows:
		free_row = free_rows[0]
		if len(free_rows) > 1:
			to_remove += free_rows[1:]

		for f in update_fields:
			free_row.set(f, free_item_data.get(f))

		if free_item_data.get("price_list_rate"):
			free_row.price_list_rate = flt(free_item_data.get("price_list_rate"))

		if free_item_data.get("uom"):
			free_row.uom = free_item_data.get("uom")
			free_row.conversion_factor = flt(get_conversion_factor(free_row.item_code, free_row.uom).get("conversion_factor") or 1)
	else:
		position = -1
		if row and row in doc.items:
			position = doc.items.index(row) + 1

		free_row = doc.append("items", free_item_data, position=position)

		# price list rate is required to apply free item rate as discount
		if set_missing_values or (free_item_data.get("price_list_rate") is None and free_item_data.get("rate")):
			doc.set_missing_item_details_for_row(free_row, skip_pricing_rules=True, for_validate=for_validate)

	# free item data may have been calculated without price list rate (for validate)
	set_free_item_rate_and_discount(free_row, free_item_data.get("rate"))

	for d in to_remove:
		doc.items.remove(d)

	if to_remove:
		for i, d in enumerate(doc.items):
			d.idx = i + 1


def remove_free_item_pricing_rules(doc):
	if doc.get("ignore_pricing_rule"):
		return

	free_rows = [d for d in doc.items if is_product_discount_rule_free_item(d)]
	to_remove = []
	for free_row in free_rows:
		free_item_pricing_rule = free_row.get("pricing_rules")
		if not free_item_pricing_rule:
			continue

		main_item_code = None
		free_item_code = None
		try:
			pr_doc = frappe.get_cached_doc("Pricing Rule", free_item_pricing_rule)
			if pr_doc.mix_and_match:
				continue

			free_item_code = free_row.item_code if pr_doc.same_item else pr_doc.get("free_item")
			main_item_code = free_row.item_code if pr_doc.same_item else None
		except frappe.DoesNotExistError:
			pass

		if not free_item_code or free_row.item_code != free_item_code:
			to_remove.append(free_row)
			continue

		main_item_found = False
		for d in doc.get("items"):
			if d == free_row:
				continue

			applied_pricing_rules = get_applied_pricing_rules(d.get("pricing_rules"))
			if free_item_pricing_rule in applied_pricing_rules and (not main_item_code or d.item_code == main_item_code):
				main_item_found = True
				break

		if not main_item_found:
			to_remove.append(free_row)

	for d in to_remove:
		doc.items.remove(d)

	if to_remove:
		for i, d in enumerate(doc.items):
			d.idx = i + 1


def apply_mix_and_match_product_discount_rules(doc):
	def get_free_rows():
		return [d for d in pr_item_rows if d.get("is_free_item")]

	def get_free_row():
		free_rows = get_free_rows()
		return free_rows[0] if free_rows else None

	def get_paid_rows():
		return [d for d in pr_item_rows if not d.get("is_free_item")]

	def get_paid_row():
		paid_rows = get_paid_rows()
		return paid_rows[0] if paid_rows else None

	def duplicate_and_swap_row(row, prepend=False):
		new_row = frappe.copy_doc(row)
		new_row.qty = 0
		new_row.stock_qty = 0
		new_row.pricing_rules = pr_doc.name
		swap_free_paid_row(new_row)

		position = -1
		if row in doc.items:
			position = doc.items.index(row)
			if not prepend:
				position += 1

		doc.append("items", new_row, position=position)

		return new_row

	def swap_free_paid_row(row):
		if row.get("is_free_item"):
			swap_free_paid_uom(row, 0)
			row.is_free_item = 0
			row.discount_percentage = 0
			row.discount_amount = 0
			row.rate = row.get("rate_with_margin") or row.get("price_list_rate") or row.get("rate") or None
		else:
			swap_free_paid_uom(row, 1)
			row.is_free_item = 1
			set_free_item_rate(row)

	def set_free_item_rate(row):
		if row.get("is_free_item"):
			set_free_item_rate_and_discount(row, pr_doc.free_item_rate)

	def adjust_qty(row, diff):
		set_free_item_uom(row)
		row.stock_qty = flt(flt(row.stock_qty) + diff, 6)
		row.qty = flt(row.stock_qty / (flt(row.conversion_factor) or 1), 6)

	def set_free_item_uom(row):
		if pr_doc.free_item_uom and row.get("is_free_item"):
			row.uom = pr_doc.free_item_uom
			set_conversion_factor(row)

	def swap_free_paid_uom(row, new_is_free_item):
		if new_is_free_item and pr_doc.free_item_uom:
			set_free_item_uom(row)
			return

		paid_rows = [d for d in pr_item_rows if not d.get("is_free_item") and d != row]
		paid_row = paid_rows[0] if paid_rows else None
		if paid_row:
			row.uom = paid_row.uom
			set_conversion_factor(row)

	def set_conversion_factor(row):
		row.conversion_factor = flt(
			get_conversion_factor(row.item_code, row.uom).get("conversion_factor") or 1
		)

	if not doc.get("mix_and_match_pricing_rules"):
		return
	if doc.get("ignore_pricing_rule"):
		return

	doc.set_qty_as_per_stock_uom()

	to_remove = []
	for pricing_rule in doc.get("mix_and_match_pricing_rules"):
		pr_rows = [d for d in doc.items if pricing_rule in get_applied_pricing_rules(d.get("pricing_rules"))]
		if not pr_rows:
			continue

		pr_doc = frappe.get_cached_doc("Pricing Rule", pricing_rule)
		free_item_map = get_mix_and_match_free_item_map(pr_doc, doc, pr_rows)

		# validate only
		if pr_doc.get("validate_applied_rule"):
			if doc.get("_mix_and_match_pricing_rules_validated") and pricing_rule in doc.get("_mix_and_match_pricing_rules_validated"):
				continue

			valid_free_items = {k: v for (k, v) in free_item_map.items() if flt(v)}
			if valid_free_items:
				validation_free_rows = [d for d in pr_rows if d.get("is_free_item") or not d.get("rate")]
				if not validation_free_rows:
					free_item_list = []
					for free_item_code, rule_free_qty in valid_free_items.items():
						free_item_list.append(_("{0} {1} of Item {2}").format(
							frappe.bold(frappe.format(rule_free_qty, df=pr_rows[0].meta.get_field("qty"))),
							frappe.bold(frappe.get_cached_value("Item", free_item_code, "stock_uom")),
							frappe.bold(free_item_code),
						))

					free_item_txt = ", ".join(free_item_list)

					frappe.msgprint(_("Pricing Rule {0} is not applied, {1} should be considered as free").format(
						frappe.utils.get_link_to_form("Pricing Rule", pricing_rule),
						free_item_txt,
					))

					if not doc.get("_mix_and_match_pricing_rules_validated"):
						doc._mix_and_match_pricing_rules_validated = set()
					doc._mix_and_match_pricing_rules_validated.add(pricing_rule)

			continue

		# apply
		pr_item_codes = set([d.item_code for d in pr_rows if d.item_code])
		for item_code in pr_item_codes:
			rule_free_qty = flt(free_item_map.get(item_code), 6)
			pr_item_rows = [d for d in pr_rows if d.item_code == item_code]
			if not pr_item_rows:
				continue

			doc_free_qty = flt(sum(d.stock_qty for d in pr_item_rows if d.get("is_free_item")), 6)
			if doc_free_qty == rule_free_qty:
				free_row = get_free_row()
				if free_row:
					adjust_qty(free_row, 0)
					set_free_item_rate(free_row)
				continue

			difference = doc_free_qty - rule_free_qty
			reduce_diff = difference

			# reduce first then add
			if difference < 0:
				paid_rows = get_paid_rows()
				for paid_row in reversed(paid_rows):
					diff = -flt(paid_row.stock_qty) if abs(reduce_diff) > flt(paid_row.stock_qty) else reduce_diff
					reduce_diff -= diff
					adjust_qty(paid_row, diff)
					if not paid_row.stock_qty:
						if not get_free_row():
							swap_free_paid_row(paid_row)
						else:
							to_remove.append(paid_row)

				free_row = get_free_row()
				if not free_row:
					free_row = duplicate_and_swap_row(get_paid_row())
				adjust_qty(free_row, -difference)
			else:
				free_rows = get_free_rows()
				for free_row in reversed(free_rows):
					diff = flt(free_row.stock_qty) if abs(reduce_diff) > flt(free_row.stock_qty) else reduce_diff
					reduce_diff -= diff
					adjust_qty(free_row, -diff)
					if not free_row.stock_qty:
						if not get_paid_row():
							swap_free_paid_row(free_row)
						else:
							to_remove.append(free_row)

				paid_row = get_paid_row()
				if not paid_row:
					paid_row = duplicate_and_swap_row(get_free_row(), prepend=True)
				adjust_qty(paid_row, difference)

	for d in to_remove:
		doc.remove(d)

	if to_remove:
		for i, d in enumerate(doc.items):
			d.idx = i + 1


def get_mix_and_match_free_item_map(pr_doc, doc, pr_rows):
	free_item_map = {}

	if not pr_rows:
		return free_item_map

	pr_rows = sorted(
		reversed(pr_rows),
		key=lambda d: flt(d.get("rate_with_margin") or d.get("price_list_rate") or d.get("rate"))
	)
	example_row = [d for d in pr_rows if not d.get("is_free_item")] or pr_rows
	example_row = example_row[0]

	free_qty, free_item_uom = calculate_free_qty_and_uom(pr_doc, example_row, doc, rows=pr_rows)
	remaining_free_qty = free_qty

	for row in pr_rows:
		if flt(remaining_free_qty, 6) <= 0:
			break

		if flt(row.stock_qty) >= remaining_free_qty:
			free_item_map.setdefault(row.item_code, 0)
			free_item_map[row.item_code] += remaining_free_qty
			remaining_free_qty = 0
		else:
			free_item_map.setdefault(row.item_code, 0)
			free_item_map[row.item_code] += flt(row.stock_qty)
			remaining_free_qty -= flt(row.stock_qty)
			remaining_free_qty = flt(remaining_free_qty, 6)

	for item_code in free_item_map:
		free_item_map[item_code] = flt(free_item_map[item_code], 6)

	return free_item_map


def get_pricing_rule_apply_on_data(pr_doc, other_items=False):
	apply_on_data = []

	if other_items:
		apply_on_field = frappe.scrub(pr_doc.apply_rule_on_other)
		if pr_doc.apply_rule_on_other:
			if apply_on_field == "item_group":
				apply_on_data.extend(get_item_group_subtree(pr_doc.get("other_" + apply_on_field)))
			else:
				apply_on_data.append(pr_doc.get("other_" + apply_on_field))
	else:
		apply_on_table_field = apply_on_table.get(pr_doc.get('apply_on'))
		apply_on_field = frappe.scrub(pr_doc.get('apply_on'))
		for d in pr_doc.get(apply_on_table_field):
			if apply_on_field == "item_group":
				apply_on_data.extend(get_item_group_subtree(d.get(apply_on_field)))
			else:
				apply_on_data.append(d.get(apply_on_field))

	return list(set(apply_on_data))


def is_product_discount_rule_free_item(row):
	if not row.get("is_free_item"):
		return False

	for pricing_rule in get_applied_pricing_rules(row.get("pricing_rules")):
		if frappe.get_cached_value("Pricing Rule", pricing_rule, "price_or_product_discount") == "Product":
			return True

	return False


def validate_coupon_code(coupon_name):
	coupon = frappe.get_doc("Coupon Code", coupon_name)

	if coupon.valid_from:
		if getdate(coupon.valid_from) > getdate():
			frappe.throw(_("Sorry, this coupon code's validity has not started"))
	if coupon.valid_upto:
		if getdate(coupon.valid_upto) < getdate():
			frappe.throw(_("Sorry, this coupon code's validity has expired"))

	if coupon.used >= coupon.maximum_use:
		frappe.throw(_("Sorry, this coupon code is no longer valid"))


def update_coupon_code_count(coupon_name, transaction_type):
	coupon = frappe.get_doc("Coupon Code", coupon_name, for_update=True)
	if coupon:
		if transaction_type == "used":
			if coupon.used < coupon.maximum_use:
				coupon.used = coupon.used+1
				coupon.save(ignore_permissions=True)
			else:
				frappe.throw(_("{0} Coupon used are {1}. Allowed quantity is exhausted").format(coupon.coupon_code,coupon.used))
		elif transaction_type == 'cancelled':
			if coupon.used > 0:
				coupon.used = coupon.used - 1
				coupon.save(ignore_permissions=True)
