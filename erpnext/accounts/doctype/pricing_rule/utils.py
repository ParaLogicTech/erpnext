# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

import frappe
from erpnext.setup.doctype.item_group.item_group import get_item_group_subtree
from erpnext.stock.doctype.warehouse.warehouse import get_child_warehouses
from erpnext.stock.get_item_details import get_conversion_factor, get_default_income_account, determine_selling_or_buying
from frappe import _
from frappe.utils import cint, flt, cstr, get_link_to_form, getdate, today
import copy
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

	pricing_rules = filter_pricing_rules_with_item_price_check(pricing_rules, args)
	pricing_rules = filter_pricing_rules_based_on_condition(pricing_rules, args, doc=doc)
	pricing_rules = filter_pricing_rules_based_on_coupon_code(pricing_rules, args)

	rules = []

	if not pricing_rules:
		return []

	if apply_multiple_pricing_rules(pricing_rules):
		pricing_rules = sorted(pricing_rules, key=lambda d: cint(d.priority), reverse=True)
		for pricing_rule in pricing_rules:
			pricing_rule = filter_pricing_rules(args, pricing_rule, doc)
			if pricing_rule:
				rules.append(pricing_rule)
	else:
		pricing_rule = filter_pricing_rules(args, pricing_rules, doc)
		if pricing_rule:
			rules.append(pricing_rule)

	return rules


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
			other_item_conditions.append(f"{child_table}.other_item_code = %(variant_of)s")
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
		from `tabPricing Rule`, {child_table}
		where
			(
				({item_conditions})
				or (({other_item_conditions}) and ifnull(`tabPricing Rule`.apply_rule_on_other, '') != '')
			)
			and {child_table}.parent = `tabPricing Rule`.name
			and `tabPricing Rule`.disable = 0
			and `tabPricing Rule`.{args.selling_or_buying} = 1
			{parent_doc_conditions}
			{warehouse_conditions}
		order by `tabPricing Rule`.priority desc, `tabPricing Rule`.name desc
	""", values, as_dict=1) or []

	return pricing_rules


def filter_pricing_rules_based_on_condition(pricing_rules, args, doc=None):
	filtered = []
	for d in pricing_rules:
		if cstr(d.condition).strip():
			if evaluate_pricing_rule_condition(d, args, doc=doc):
				filtered.append(d)
		else:
			filtered.append(d)

	return filtered


def filter_pricing_rules_based_on_coupon_code(pricing_rules, args):
	filtered = []
	for d in pricing_rules:
		if d.coupon_code_based:
			if (
				args.coupon_code
				and frappe.db.get_value("Coupon Code", args.coupon_code, "pricing_rule", cache=1) == d.name
			):
				filtered.append(d)
		else:
			filtered.append(d)

	return filtered


def evaluate_pricing_rule_condition(pricing_rule, args, doc=None):
	from frappe.utils.safe_exec import get_safe_globals

	if not pricing_rule.condition:
		return True

	eval_globals = get_safe_globals()
	context = frappe._dict({
		"item_code": args.get("item_code"),
		"args": args,
		"doc": doc or frappe._dict(),
		"rule": pricing_rule,
	})

	if frappe.safe_eval(pricing_rule.condition, eval_globals, context):
		return True


def apply_multiple_pricing_rules(pricing_rules):
	apply_multiple_rule = [d.apply_multiple_pricing_rules
		for d in pricing_rules if d.apply_multiple_pricing_rules]

	if not apply_multiple_rule: return False

	if (apply_multiple_rule
		and len(apply_multiple_rule) == len(pricing_rules)):
		return True


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
	return frappe.local_cache("pricing_rule_get_tree_parent_groups", key, generator)


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


def filter_pricing_rules(args, pricing_rules, doc=None):
	if not isinstance(pricing_rules, list):
		pricing_rules = [pricing_rules]

	original_pricing_rule = copy.copy(pricing_rules)

	# filter for qty
	if pricing_rules:
		stock_qty = flt(args.get('stock_qty'))
		amount = flt(args.get('price_list_rate')) * flt(args.get('qty'))

		if pricing_rules[0].apply_rule_on_other:
			field = frappe.scrub(pricing_rules[0].apply_rule_on_other)

			if (field and pricing_rules[0].get('other_' + field) != args.get(field)): return

		pr_doc = frappe.get_cached_doc('Pricing Rule', pricing_rules[0].name)

		if pricing_rules[0].mixed_conditions and doc:
			stock_qty, amount, items = get_qty_and_rate_for_mixed_conditions(doc, pr_doc, args)
			for pricing_rule_args in pricing_rules:
				pricing_rule_args.apply_rule_on_other_items = items

		elif pricing_rules[0].is_cumulative:
			items = [args.get(frappe.scrub(pr_doc.get('apply_on')))]
			data = get_qty_amount_data_for_cumulative(pr_doc, args, items)

			if data:
				stock_qty += data[0]
				amount += data[1]

		if pricing_rules[0].apply_rule_on_other and not pricing_rules[0].mixed_conditions and doc:
			pricing_rules = get_qty_and_rate_for_other_item(doc, pr_doc, pricing_rules) or []
		else:
			pricing_rules = filter_pricing_rules_for_qty_amount(stock_qty, amount, pricing_rules, args)

		if not pricing_rules:
			for d in original_pricing_rule:
				if not d.threshold_percentage: continue

				msg = validate_quantity_and_amount_for_suggestion(d, stock_qty,
					amount, args.get('item_code'), args.get('selling_or_buying'))

				if msg:
					return {'suggestion': msg, 'item_code': args.get('item_code')}

		# add variant_of property in pricing rule
		for p in pricing_rules:
			if p.item_code and args.variant_of:
				p.variant_of = args.variant_of
			else:
				p.variant_of = None

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
			pricing_rules = list(filter(lambda x: x.for_price_list==args.price_list, pricing_rules)) \
				or pricing_rules

	if len(pricing_rules) > 1 and not args.for_shopping_cart:
		frappe.throw(_("Multiple Price Rules exists with same criteria, please resolve conflict by assigning priority. Pricing Rules:<ol>{0}</ol>")
			.format("".join([f"<li>{frappe.utils.get_link_to_form('Pricing Rule', d.name)}</li>" for d in pricing_rules])), MultiplePricingRuleConflict)
	elif pricing_rules:
		return pricing_rules[0]


def validate_quantity_and_amount_for_suggestion(args, qty, amount, item_code, selling_or_buying):
	fieldname, msg = '', ''
	type_of_transaction = 'purchase' if selling_or_buying == 'buying' else 'sale'

	for field, value in {'min_qty': qty, 'min_amt': amount}.items():
		if (args.get(field) and value < args.get(field)
			and (args.get(field) - cint(args.get(field) * args.threshold_percentage * 0.01)) <= value):
			fieldname = field

	for field, value in {'max_qty': qty, 'max_amt': amount}.items():
		if (args.get(field) and value > args.get(field)
			and (args.get(field) + cint(args.get(field) * args.threshold_percentage * 0.01)) >= value):
			fieldname = field

	if fieldname:
		msg = _("""If you {0} {1} quantities of the item <b>{2}</b>, the scheme <b>{3}</b>
			will be applied on the item.""").format(type_of_transaction, args.get(fieldname), item_code, args.rule_description)

		if fieldname in ['min_amt', 'max_amt']:
			msg = _("""If you {0} {1} worth item <b>{2}</b>, the scheme <b>{3}</b> will be applied on the item.
				""").format(frappe.fmt_money(type_of_transaction, args.get(fieldname)), item_code, args.rule_description)

		frappe.msgprint(msg)

	return msg


def filter_pricing_rules_for_qty_amount(stock_qty, amount, pricing_rules, args=None):
	args = args or frappe._dict()
	stock_qty = flt(stock_qty, 6)
	amount = flt(amount, 6)

	rules = []
	for rule in pricing_rules:
		item_code = rule.get("item_code") or args.get("item_code")

		conversion_factor = 1
		if item_code and rule.get("uom"):
			conversion_factor = flt(get_conversion_factor(item_code, rule.uom).get("conversion_factor") or 1)

		min_qty = flt(flt(rule.min_qty) * conversion_factor, 6)
		max_qty = flt(flt(rule.max_qty) * conversion_factor, 6)
		min_amt = flt(flt(rule.min_amt) * conversion_factor, 6)
		max_amt = flt(flt(rule.min_amt) * conversion_factor, 6)

		if stock_qty < min_qty or (max_qty and stock_qty > max_qty):
			continue
		if amount < min_amt or (max_amt and amount > max_amt):
			continue

		rules.append(rule)

	return rules


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
			if filtered_rules: break

	return filtered_rules or pricing_rules


def get_qty_and_rate_for_mixed_conditions(doc, pr_doc, args):
	items = get_pricing_rule_items(pr_doc) or []
	apply_on_field = frappe.scrub(pr_doc.get("apply_on"))

	sum_qty = 0
	sum_amt = 0
	if items and doc.get("items"):
		for row in doc.get('items'):
			if row.get(apply_on_field) not in items:
				continue

			if pr_doc.mixed_conditions:
				stock_qty = flt(row.get("qty")) * flt(row.get("conversion_factor"))
				amount = flt(row.get("qty")) * (flt(row.get("price_list_rate")) or flt(args.get("rate")))

				sum_qty += stock_qty
				sum_amt += amount

		if pr_doc.is_cumulative:
			data = get_qty_amount_data_for_cumulative(pr_doc, doc, items)

			if data and data[0]:
				sum_qty += data[0]
				sum_amt += data[1]

	return sum_qty, sum_amt, items


def get_qty_and_rate_for_other_item(doc, pr_doc, pricing_rules):
	other_items = get_pricing_rule_items(pr_doc, other_items=True)
	apply_on_table_field = apply_on_table.get(pr_doc.get("apply_on"))
	apply_on_field = frappe.scrub(pr_doc.get("apply_on"))

	items = []
	for d in pr_doc.get(apply_on_table_field):
		if apply_on_field == "item_group":
			items.extend(get_item_group_subtree(d.get(apply_on_field)))
		else:
			items.append(d.get(apply_on_field))

	for row in doc.items:
		if row.get(apply_on_field) not in items or not row.get("qty"):
			continue

		stock_qty = flt(row.get("qty")) * flt(row.get("conversion_factor"))
		amount = flt(row.get("qty")) * (flt(row.get("price_list_rate")) or flt(row.get("rate")))
		pricing_rules = filter_pricing_rules_for_qty_amount(stock_qty, amount, pricing_rules, args=row)

		if pricing_rules and pricing_rules[0]:
			pricing_rules[0].apply_rule_on_other_items = other_items
			return pricing_rules


def get_qty_amount_data_for_cumulative(pr_doc, doc, items=None):
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

	if items:
		condition = f" and `tab{child_doctype}`.{apply_on_field} in ({','.join(['%s'] * len(items))})"
		values.extend(items)

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

	sum_qty = 0
	sum_amt = 0
	for data in data_set:
		sum_qty += data.get('stock_qty')
		sum_amt += data.get('amount')

	return [sum_qty, sum_amt]


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
		pricing_rules = filter_pricing_rules_for_qty_amount(doc.total_qty,
			doc.total, pricing_rules)

		for d in pricing_rules:
			if d.price_or_product_discount == 'Price':
				if d.apply_discount_on:
					doc.set('apply_discount_on', d.apply_discount_on)

				for field in ['additional_discount_percentage', 'discount_amount']:
					pr_field = ('discount_percentage'
						if field == 'additional_discount_percentage' else field)

					if not d.get(pr_field): continue

					if d.validate_applied_rule and doc.get(field) < d.get(pr_field):
						frappe.msgprint(_("User has not applied rule on the invoice {0}")
							.format(doc.name))
					else:
						doc.set(field, d.get(pr_field))

				doc.calculate_taxes_and_totals()
			elif d.price_or_product_discount == 'Product':
				item_details = frappe._dict({'parenttype': doc.doctype})
				get_product_discount_rule(d, item_details, doc=doc)
				apply_pricing_rule_for_free_items(doc, item_details.free_item_data)
				doc.set_missing_values()


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
			return [d for d in pricing_rules.split(',') if d]

	return []


def get_product_discount_rule(pricing_rule, item_details, args=None, doc=None):
	free_item = pricing_rule.free_item
	if pricing_rule.same_item:
		free_item = item_details.item_code or args.item_code

	if not free_item:
		frappe.throw(_("Free item not set in the pricing rule {0}")
			.format(get_link_to_form("Pricing Rule", pricing_rule.name)))

	item_details.free_item_data = {
		'item_code': free_item,
		'qty': pricing_rule.free_qty or 1,
		'rate': pricing_rule.free_item_rate or 0,
		'price_list_rate': pricing_rule.free_item_rate or 0,
		'is_free_item': 1
	}

	item_data = frappe.get_cached_value('Item', free_item, ['item_name',
		'description', 'stock_uom'], as_dict=1)

	item_details.free_item_data.update(item_data)
	item_details.free_item_data['uom'] = pricing_rule.free_item_uom or item_data.stock_uom
	item_details.free_item_data['conversion_factor'] = get_conversion_factor(free_item,
		item_details.free_item_data['uom']).get("conversion_factor", 1)

	if item_details.get("parenttype") == 'Purchase Order':
		item_details.free_item_data['schedule_date'] = doc.schedule_date if doc else today()

	if item_details.get("parenttype") == 'Sales Order':
		item_details.free_item_data['delivery_date'] = doc.delivery_date if doc else today()

	item_details.free_item_data['income_account'] = get_default_income_account(free_item, args)


def apply_pricing_rule_for_free_items(doc, pricing_rule_args, set_missing_values=False):
	if pricing_rule_args.get('item_code'):
		items = [d.item_code for d in doc.items
			if d.item_code == (pricing_rule_args.get("item_code")) and d.is_free_item]

		if not items:
			doc.append('items', pricing_rule_args)


def get_pricing_rule_items(pr_doc, other_items=False):
	apply_on_data = []
	apply_on = frappe.scrub(pr_doc.get('apply_on'))

	pricing_rule_apply_on = apply_on_table.get(pr_doc.get('apply_on'))

	if other_items:
		if pr_doc.apply_rule_on_other:
			apply_on = frappe.scrub(pr_doc.apply_rule_on_other)
			apply_on_data.append(pr_doc.get("other_" + apply_on))
	else:
		for d in pr_doc.get(pricing_rule_apply_on):
			if apply_on == "item_group":
				apply_on_data.extend(get_item_group_subtree(d.get(apply_on)))
			else:
				apply_on_data.append(d.get(apply_on))

	return list(set(apply_on_data))


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
	coupon=frappe.get_doc("Coupon Code", coupon_name, for_update=True)
	if coupon:
		if transaction_type=='used':
			if coupon.used<coupon.maximum_use:
				coupon.used=coupon.used+1
				coupon.save(ignore_permissions=True)
			else:
				frappe.throw(_("{0} Coupon used are {1}. Allowed quantity is exhausted").format(coupon.coupon_code,coupon.used))
		elif transaction_type=='cancelled':
			if coupon.used>0:
				coupon.used=coupon.used-1
				coupon.save(ignore_permissions=True)


def filter_pricing_rules_with_item_price_check(pricing_rules, args):
	from erpnext.stock.get_item_details import get_price_list_rate_for
	filtered = []

	for pricing_rule in pricing_rules:
		if pricing_rule.get('ignore_if_item_price_available'):
			price_list = pricing_rule.for_price_list or args.get('price_list')

			item_price_args = {
				"item_code": args.get("item_code"),
				"price_list": price_list,
				"transaction_date": args.get("transaction_date") or today(),
				"uom": args.get("uom")
			}

			item_price_data = get_price_list_rate_for(args.get("item_code"), price_list, item_price_args)

			if item_price_data:
				continue

		filtered.append(pricing_rule)

	return filtered
