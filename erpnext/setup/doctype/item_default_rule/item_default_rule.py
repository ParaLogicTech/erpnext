# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, cstr
from frappe.model.document import Document


def get_transaction_filter_fields():
	fields = ["company", "transaction_type"]
	fields += frappe.get_hooks("item_default_rule_transaction_filter_fields")

	hooks = frappe.get_hooks("update_item_default_rule_transaction_filter_fields")
	for method in hooks:
		frappe.get_attr(method)(fields)

	return fields


def get_item_filter_fields():
	fields = ["item_code", "item_source", "brand", "item_group"]
	fields += frappe.get_hooks("item_default_rule_item_filter_fields")

	hooks = frappe.get_hooks("update_item_default_rule_item_filter_fields")
	for method in hooks:
		frappe.get_attr(method)(fields)

	return fields


def get_filter_fields():
	return get_transaction_filter_fields() + get_item_filter_fields()


class ItemDefaultRule(Document):
	def validate(self):
		self.validate_duplicate()
		self.validate_item_tax()

	def on_change(self):
		clear_item_default_rule_cache()

	def after_rename(self, old_name, new_name, merge):
		clear_item_default_rule_cache()

	def validate_duplicate(self):
		filters = {}

		if not self.is_new():
			filters['name'] = ['!=', self.name]

		for f in get_filter_fields():
			if self.get(f):
				filters[f] = self.get(f)
			else:
				filters[f] = ['is', 'not set']

		existing = frappe.get_all("Item Default Rule", filters=filters)
		if existing:
			frappe.throw(_("{0} already exists with the same filters")
				.format(frappe.get_desk_link("Item Default Rule", existing[0].name)))

	def validate_item_tax(self):
		"""Check whether Tax Rate is not entered twice for same Tax Type"""
		check_list = []
		for d in self.get('taxes'):
			if d.item_tax_template:
				key = (d.item_tax_template, cstr(d.tax_category))
				if key in check_list:
					frappe.throw(_("{0} entered twice in Item Tax").format(d.item_tax_template))
				else:
					check_list.append(key)

	def get_applicable_rule_dict(self, filters):
		required_filters = self.get_required_filters()

		if required_filters:
			# check if required filters matches
			required_filters_matched = True
			for field, required_value in required_filters.items():
				if field == "item_code":
					if not self.match_item(required_value, filters.get(field)):
						required_filters_matched = False
						break
				elif field == "item_group":
					if not self.match_tree("Item Group", required_value, filters.get(field)):
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
		for f in get_filter_fields():
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

		if rule_dict.get('item_group'):
			rule_dict['item_group_lft'] = frappe.get_cached_value("Item Group", rule_dict.get('item_group'), 'lft')

		return rule_dict


def get_item_default_values(item, transaction=None, cache=True):
	filters = get_filters_dict(item, transaction)
	return get_default_values_for_filters(filters, cache=cache)


def get_default_values_for_filters(filters, cache=True):
	def generator():
		applicable_rules = get_applicable_rules_for_filters(filters)
		return get_default_values_dict(applicable_rules)

	if cache:
		key_json = frappe.as_json(filters, indent=None, separators=(",", ":"))
		return frappe.local_cache("get_item_default_rule_values_for_filters", key_json, generator)
	else:
		return generator()


def get_default_values_dict(applicable_rules, filter_sort=None):
	def sorting_function(d):
		no_of_matches = len(d.required_filters)

		filter_precedences = []
		for k in d.required_filters:
			if k in filter_sort:
				index = filter_sort.index(k)

				if k == 'item_code':
					filter_precedences.append((index, cint(not d.get('variant_of'))))
				elif k == 'item_group':
					filter_precedences.append((index, -cint(d.item_group_lft)))
				else:
					filter_precedences.append((index,))
			else:
				filter_precedences.append(999999)

		filter_precedences = sorted(filter_precedences)

		return tuple([-no_of_matches] + filter_precedences)

	# sort: more matches first, precendent filters first
	if not filter_sort:
		filter_sort = get_filter_fields()

	applicable_rules = sorted(applicable_rules, key=lambda d: sorting_function(d))

	rule_meta = frappe.get_meta("Item Default Rule")
	values = frappe._dict()
	for rule in applicable_rules:
		for fieldname, value in rule.items():
			if fieldname == "item_default_rule_name":
				continue
			if fieldname in get_filter_fields():
				continue

			df = rule_meta.get_field(fieldname)
			if not df:
				continue

			is_numeric = df.fieldtype in frappe.model.numeric_fieldtypes
			if is_numeric:
				value_empty = value is None
			else:
				value_empty = not value

			if not value_empty:
				if fieldname == "taxes":
					values.setdefault(fieldname, [])
					values[fieldname] += value
				elif fieldname == "min_margin":
					if rule.get("validate_min_margin") == "Yes" and values.get(fieldname) is None:
						values[fieldname] = value
				elif not values.get(fieldname):
					values[fieldname] = value

	return values


def get_applicable_rules(item, transaction=None):
	filters = get_filters_dict(item, transaction)
	return get_applicable_rules_for_filters(filters)


def get_filters_dict(item, transaction=None):
	if not item:
		item = {}
	if not transaction:
		transaction = {}

	if isinstance(item, str):
		item = frappe.get_cached_doc("Item", item)
	if isinstance(transaction, Document):
		transaction = transaction.as_dict()

	filters = frappe._dict()

	if not item:
		for f in get_filter_fields():
			if transaction.get(f):
				filters[f] = transaction.get(f)
	else:
		for f in get_item_filter_fields():
			if item.get(f):
				filters[f] = item.get(f)
		for f in get_transaction_filter_fields():
			if transaction.get(f):
				filters[f] = transaction.get(f)

	if item:
		filters["item_code"] = item.get("name")
	if 'transaction_type_name' in transaction:
		filters['transaction_type'] = transaction.get('transaction_type_name')

	return filters


def get_applicable_rules_for_filters(filters):
	if not filters:
		filters = frappe._dict()

	rules = get_item_default_rule_docs()

	applicable_rules = []
	for rule in rules:
		rule_dict = rule.get_applicable_rule_dict(filters)
		if rule_dict:
			applicable_rules.append(rule_dict)

	return applicable_rules


def get_item_default_rule_docs():
	names = get_item_default_rule_names()
	docs = [frappe.get_cached_doc("Item Default Rule", name) for name in names]
	return docs


def get_item_default_rule_names():
	def generator():
		names = [d.name for d in frappe.get_all('Item Default Rule')]
		return names

	return frappe.cache.get_value("item_default_rule_names", generator)


def clear_item_default_rule_cache():
	frappe.cache.delete_value('item_default_rule_names')
