# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt
from frappe.model.document import Document

user_filter_fields = ['user', 'role']
transaction_filter_fields = ['company']
customer_filter_fields = ['customer', 'customer_group', 'territory']
item_filter_fields = ['item_code', 'item_source', 'brand', 'item_group']
applies_to_filter_fileds = ['applies_to_item', 'applies_to_item_brand', 'applies_to_item_group']

filter_fields = user_filter_fields + transaction_filter_fields + customer_filter_fields + item_filter_fields + applies_to_filter_fileds


class DiscountRule(Document):
	def validate(self):
		self.validate_duplicate()
		self.validate_max_discount()

	def on_change(self):
		clear_discount_rule_cache()

	def after_rename(self, old_name, new_name, merge):
		clear_discount_rule_cache()

	def validate_duplicate(self):
		filters = {}

		if not self.is_new():
			filters['name'] = ['!=', self.name]

		for f in filter_fields:
			if self.get(f):
				filters[f] = self.get(f)
			else:
				filters[f] = ['is', 'not set']

		existing = frappe.get_all("Discount Rule", filters=filters)
		if existing:
			frappe.throw(_("{0} already exists with the same filters")
				.format(frappe.get_desk_link("Discount Rule", existing[0].name)))

	def validate_max_discount(self):
		if flt(self.max_discount) < 0:
			frappe.throw(_("Maximum Discount cannot be negative"))
		if flt(self.max_discount) > 100:
			frappe.throw(_("Maximum Discount cannot be more than 100%"))

	def get_applicable_rule_dict(self, filters):
		required_filters = self.get_required_filters()

		if required_filters:
			# check if required filters matches
			required_filters_matched = True
			for field, required_value in required_filters.items():
				if field in ("item_code", "applies_to_item"):
					if not self.match_item(required_value, filters.get(field)):
						required_filters_matched = False
						break
				elif field in ("item_group", "applies_to_item_group"):
					if not self.match_tree("Item Group", required_value, filters.get(field)):
						required_filters_matched = False
						break
				elif field == "customer_group":
					if not self.match_tree("Customer Group", required_value, filters.get(field)):
						required_filters_matched = False
						break
				elif field == "territory":
					if not self.match_tree("Territory", required_value, filters.get(field)):
						required_filters_matched = False
						break
				elif field == "role":
					if required_value not in filters.get(field, []):
						required_filters_matched = False
						break
				elif filters.get(field) != required_value:
					required_filters_matched = False
					break
		else:
			# global rule, applicable to all
			required_filters_matched = True

		if required_filters_matched:
			return self.get_rule_match_dict(required_filters)
		else:
			return None

	def match_item(self, required, actual):
		actual_variant_and_template = []
		if actual:
			item_doc = frappe.get_cached_doc("Item", actual)
			actual_variant_and_template.append(actual)
			if item_doc.variant_of:
				actual_variant_and_template.append(item_doc.variant_of)

		return required in actual_variant_and_template

	def match_tree(self, doctype, required, actual):
		meta = frappe.get_meta(doctype)
		parent_field = meta.nsm_parent_field

		actual_ancestors = []
		if actual:
			current_name = actual
			while current_name:
				current_doc = frappe.get_cached_doc(doctype, current_name)
				actual_ancestors.append(current_doc.name)
				current_name = current_doc.get(parent_field)

		return required in actual_ancestors

	def get_required_filters(self):
		required_filters = frappe._dict()
		for f in filter_fields:
			if self.get(f):
				required_filters[f] = self.get(f)

		return required_filters

	def get_rule_match_dict(self, required_filters):
		rule_dict = self.as_dict()
		rule_dict.required_filters = required_filters

		if rule_dict.get('item_code'):
			variant_of = frappe.get_cached_value("Item", rule_dict.get('item_code'), 'variant_of')
			if variant_of:
				rule_dict['variant_of'] = variant_of

		if rule_dict.get('applies_to_item'):
			applies_to_variant_of = frappe.get_cached_value("Item", rule_dict.get('applies_to_item'), 'variant_of')
			if applies_to_variant_of:
				rule_dict['applies_to_variant_of'] = applies_to_variant_of

		if rule_dict.get('item_group'):
			rule_dict['item_group_lft'] = frappe.get_cached_value("Item Group", rule_dict.get('item_group'), 'lft')

		if rule_dict.get('applies_to_item_group'):
			rule_dict['applies_to_item_group_lft'] = frappe.get_cached_value("Item Group", rule_dict.get('item_group'), 'lft')

		if rule_dict.get('customer_group'):
			rule_dict['customer_group_lft'] = frappe.get_cached_value("Customer Group", rule_dict.get('customer_group'), 'lft')

		if rule_dict.get('territory'):
			rule_dict['territory_lft'] = frappe.get_cached_value("Territory", rule_dict.get('territory'), 'lft')

		return rule_dict


def get_discount_rule_values(item, transaction, user=None):
	filters = get_filters_dict(item, transaction, user)
	applicable_rules = get_applicable_rules_for_filters(filters)
	return get_discount_rule_values_dict(applicable_rules)


def get_discount_rule_values_for_filters(filters):
	applicable_rules = get_applicable_rules_for_filters(filters)
	return get_discount_rule_values_dict(applicable_rules)


def get_discount_rule_values_dict(applicable_rules, filter_sort=None):
	def sorting_function(d):
		no_of_matches = len(d.required_filters)

		filter_precedences = []
		for k in d.required_filters:
			if k in filter_sort:
				index = filter_sort.index(k)

				if k == 'item_code':
					filter_precedences.append((index, cint(not d.get('variant_of'))))
				elif k == 'applies_to_item':
					filter_precedences.append((index, cint(not d.get('applies_to_variant_of'))))
				elif k == 'item_group':
					filter_precedences.append((index, -cint(d.item_group_lft)))
				elif k == 'applies_to_item_group':
					filter_precedences.append((index, -cint(d.applies_to_item_group_lft)))
				elif k == 'customer_group':
					filter_precedences.append((index, -cint(d.customer_group_lft)))
				elif k == 'territory':
					filter_precedences.append((index, -cint(d.territory_lft)))
				elif k == 'role':
					filter_precedences.append((index, cint(d.get('role') == 'All')))
				else:
					filter_precedences.append((index,))
			else:
				filter_precedences.append(999999)

		filter_precedences = sorted(filter_precedences)

		return tuple([-no_of_matches] + filter_precedences)

	# sort: more matches first, precendent filters first
	if not filter_sort:
		filter_sort = filter_fields.copy()

	applicable_rules = sorted(applicable_rules, key=lambda d: sorting_function(d))

	rule_meta = frappe.get_meta("Discount Rule")
	values = frappe._dict()
	for rule in applicable_rules:
		for fieldname, value in rule.items():
			if fieldname == "discount_rule_name":
				continue

			if value and fieldname not in filter_fields and rule_meta.has_field(fieldname):
				if fieldname not in values:
					values[fieldname] = value

	return values


def get_applicable_rules(item, transaction, user=None):
	filters = get_filters_dict(item, transaction, user)
	return get_applicable_rules_for_filters(filters)


def get_filters_dict(item, transaction, user=None):
	if not item:
		item = {}
	if not transaction:
		transaction = {}
	if not user:
		user = frappe.session.user

	if isinstance(item, str):
		item = frappe.get_cached_doc("Item", item)
	if isinstance(transaction, Document):
		transaction = transaction.as_dict()

	customer = transaction.get("bill_to") or transaction.get("customer")
	customer = frappe.get_cached_doc("Customer", customer) if customer else {}

	applies_to_item = transaction.get("applies_to_item")
	applies_to_item = frappe.get_cached_doc("Item", applies_to_item) if applies_to_item else {}

	filters = frappe._dict()

	for f in item_filter_fields:
		if item.get(f):
			filters[f] = item.get(f)
	for f in transaction_filter_fields:
		if transaction.get(f):
			filters[f] = transaction.get(f)
	for f in customer_filter_fields:
		if customer.get(f):
			filters[f] = customer.get(f)

	if item:
		filters["item_code"] = item.get("name")

	if customer:
		filters["customer"] = customer.get("name")

	if user:
		filters["user"] = user
		filters["role"] = frappe.get_roles(user) if user else []

	if applies_to_item:
		filters["applies_to_item"] = applies_to_item.get("name")
		filters["applies_to_item_brand"] = applies_to_item.get("brand")
		filters["applies_to_item_item_group"] = applies_to_item.get("item_group")

	return filters


def get_applicable_rules_for_filters(filters):
	if not filters:
		filters = frappe._dict()

	rules = get_discount_rule_docs()

	applicable_rules = []
	for rule in rules:
		rule_dict = rule.get_applicable_rule_dict(filters)
		if rule_dict:
			applicable_rules.append(rule_dict)

	return applicable_rules


def get_discount_rule_docs():
	names = get_discount_rule_names()
	docs = [frappe.get_cached_doc("Discount Rule", name) for name in names]
	return docs


def get_discount_rule_names():
	def generator():
		names = [d.name for d in frappe.get_all('Discount Rule')]
		return names

	return frappe.cache.get_value("discount_rule_names", generator)


def clear_discount_rule_cache():
	frappe.cache.delete_value('discount_rule_names')
