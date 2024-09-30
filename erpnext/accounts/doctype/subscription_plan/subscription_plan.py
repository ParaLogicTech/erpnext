# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, fmt_money, flt
from frappe.model.document import Document
from erpnext.accounts.doctype.pricing_rule.pricing_rule import get_pricing_rule_for_item


class SubscriptionPlan(Document):
	def validate(self):
		self.validate_interval_count()

	def validate_interval_count(self):
		if self.billing_interval_count < 1:
			frappe.throw(_('Billing Interval Count cannot be less than 1'))


@frappe.whitelist()
def get_plan_rate(plan, quantity=1, customer=None):
	plan = frappe.get_doc("Subscription Plan", plan)
	if plan.price_determination == "Fixed rate":
		return plan.cost

	elif plan.price_determination == "Based on price list":
		if customer:
			customer_group = frappe.db.get_value("Customer", customer, "customer_group")
		else:
			customer_group = None

		price = get_price(item_code=plan.item, price_list=plan.price_list, customer_group=customer_group, company=None, qty=quantity)
		if not price:
			return 0
		else:
			return price.price_list_rate


def get_price(item_code, price_list, customer_group, company, qty=1):
	template_item_code = frappe.db.get_value("Item", item_code, "variant_of")

	if price_list:
		price = frappe.get_all("Item Price", fields=["price_list_rate", "currency"],
			filters={"price_list": price_list, "item_code": item_code})

		if template_item_code and not price:
			price = frappe.get_all("Item Price", fields=["price_list_rate", "currency"],
				filters={"price_list": price_list, "item_code": template_item_code})

		if price:
			pricing_rule = get_pricing_rule_for_item(frappe._dict({
				"item_code": item_code,
				"qty": qty,
				"selling_or_buying": "selling",
				"price_list": price_list,
				"customer_group": customer_group,
				"company": company,
				"conversion_rate": 1,
				"for_shopping_cart": True,
				"currency": frappe.db.get_value("Price List", price_list, "currency")
			}))

			if pricing_rule:
				if pricing_rule.pricing_rule_for == "Discount Percentage":
					price[0].price_list_rate = flt(price[0].price_list_rate * (1.0 - (flt(pricing_rule.discount_percentage) / 100.0)))

				if pricing_rule.pricing_rule_for == "Rate":
					price[0].price_list_rate = pricing_rule.price_list_rate

			price_obj = price[0]
			if price_obj:
				price_obj["formatted_price"] = fmt_money(price_obj["price_list_rate"], currency=price_obj["currency"])

				price_obj["currency_symbol"] = not cint(frappe.db.get_default("hide_currency_symbol")) \
					and (frappe.db.get_value("Currency", price_obj.currency, "symbol", cache=True) or price_obj.currency) \
					or ""

				uom_conversion_factor = frappe.db.sql("""select	C.conversion_factor
					from `tabUOM Conversion Detail` C
					inner join `tabItem` I on C.parent = I.name and C.uom = I.sales_uom
					where I.name = %s""", item_code)

				uom_conversion_factor = uom_conversion_factor[0][0] if uom_conversion_factor else 1
				price_obj["formatted_price_sales_uom"] = fmt_money(price_obj["price_list_rate"] * uom_conversion_factor, currency=price_obj["currency"])

				if not price_obj["price_list_rate"]:
					price_obj["price_list_rate"] = 0

				if not price_obj["currency"]:
					price_obj["currency"] = ""

				if not price_obj["formatted_price"]:
					price_obj["formatted_price"] = ""

			return price_obj
