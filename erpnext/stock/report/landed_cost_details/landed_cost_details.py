# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _, scrub
from frappe.utils import flt, cstr
from erpnext.selling.report.sales_details.sales_details import SalesPurchaseDetailsReport, get_itemised_taxes
import json


def execute(filters=None):
	updated_filters = {
		"qty_only": 0,
		"include_taxes": 1,
		"hide_grand_total": 1,
	}
	updated_filters.update(filters or {})

	return LandedCostDetailsReport(updated_filters, doctype="Purchase Invoice").run()


class LandedCostDetailsReport(SalesPurchaseDetailsReport):
	def set_fieldnames(self):
		super().set_fieldnames()
		self.additional_amount_fields += [
			"debit_note_amount",
			"taxes_in_valuation",
			"taxes_not_in_valuation",
		]

	def get_select_fields_and_joins(self):
		select_fields, joins = super().get_select_fields_and_joins()
		select_fields += [
			"i.debit_note_amount",
			"i.purchase_receipt",
			"i.purchase_receipt_item",
		]

		return select_fields, joins

	def get_conditions(self):
		conditions = super().get_conditions()
		conditions.append("s.is_return = 0")
		return conditions

	def get_itemised_taxes(self):
		self.itemised_tax = {}
		self.tax_account_heads = []
		self.tax_amount_fields = []
		self.tax_rate_fields = []

		if self.entries:
			self.itemised_tax, self.tax_account_heads = get_itemised_taxes(
				self.entries,
				"Purchase Taxes and Charges",
				description_as_tax_head=True,
				group_by_include_in_valuation=True,
			)
			self.tax_amount_fields = ["tax_" + scrub(tax) + "_" + cstr(include_in_valuation) for tax, include_in_valuation in self.tax_account_heads]

		self.get_landed_cost_voucher_data()

	def get_landed_cost_voucher_data(self):
		purchase_invoice_items = []
		purchase_receipt_items = set()

		for pinv_i in self.entries:
			purchase_invoice_items.append(pinv_i.name)
			if pinv_i.purchase_receipt_item:
				purchase_receipt_items.add(pinv_i.purchase_receipt_item)

		self.lcv_account_heads = set()
		self.lcv_by_pinv_item = {}
		self.lcv_by_prec_item = {}
		if not purchase_invoice_items and not purchase_receipt_items:
			return

		or_conditions = []
		if purchase_receipt_items:
			or_conditions.append("lci.purchase_receipt_item in %(purchase_receipt_items)s")
		if purchase_invoice_items:
			or_conditions.append("lci.purchase_invoice_item in %(purchase_invoice_items)s")

		or_conditions_str = " or ".join(or_conditions)

		lcv_data = frappe.db.sql(f"""
			select
				lcv.name as landed_cost_voucher,
				lci.name as landed_cost_voucher_item,
				lci.purchase_receipt_item,
				lci.purchase_invoice_item,
				lci.applicable_charges,
				lci.item_tax_detail
			from `tabLanded Cost Item` lci
			inner join `tabLanded Cost Voucher` lcv on lcv.name = lci.parent
			where lcv.docstatus = 1 and ({or_conditions_str})
		""", {
			"purchase_receipt_items": purchase_receipt_items,
			"purchase_invoice_items": purchase_invoice_items,
		}, as_dict=1)

		lcv_names = set()
		for lci in lcv_data:
			lcv_names.add(lci.landed_cost_voucher)
			if lci.purchase_invoice_item:
				self.lcv_by_pinv_item.setdefault(lci.purchase_invoice_item, []).append(lci)
			elif lci.purchase_receipt_item:
				self.lcv_by_prec_item.setdefault(lci.purchase_receipt_item, []).append(lci)

		lcv_tax_row_data = []
		if lcv_names:
			lcv_tax_row_data = frappe.db.sql(f"""
				select lct.name, lct.account_head, acc.account_name
				from `tabLanded Cost Taxes and Charges` lct
				left join `tabAccount` acc on acc.name = lct.account_head
				where lct.parent in %s
			""", [lcv_names], as_dict=1)

		lcv_tax_row_map = {}
		for lcv_t in lcv_tax_row_data:
			lcv_tax_row_map[lcv_t.name] = lcv_t

		for lcv_i in lcv_data:
			lcv_i["item_tax_map"] = {}
			item_tax_detail = json.loads(lcv_i.item_tax_detail) if lcv_i.item_tax_detail else {}

			for tax_row_name, tax_amount in item_tax_detail.items():
				if not tax_amount:
					continue

				tax_row = lcv_tax_row_map.get(tax_row_name, {})
				if not tax_row:
					continue

				tax_head = tax_row.account_name or tax_row.account_head
				self.lcv_account_heads.add(tax_head)

				item_tax_dict = lcv_i["item_tax_map"].setdefault(tax_head, frappe._dict({"tax_amount": 0}))
				item_tax_dict["tax_amount"] += tax_amount

		self.lcv_account_heads = sorted(list(self.lcv_account_heads))
		self.lcv_amount_fields = ["lcv_" + scrub(tax) for tax in self.lcv_account_heads]
		self.additional_amount_fields += self.lcv_amount_fields

	def prepare_data(self):
		super().prepare_data()

		for pinv_i in self.entries:
			pinv_i.taxes_in_valuation = 0
			pinv_i.taxes_not_in_valuation = 0

			item_taxes = self.itemised_tax.get(pinv_i.name, {})
			for (tax, include_in_valuation), tax_obj in item_taxes.items():
				tax_amount = tax_obj.get("tax_amount", 0.0)
				if include_in_valuation:
					pinv_i.taxes_in_valuation += flt(tax_amount)
				else:
					pinv_i.taxes_not_in_valuation += flt(tax_amount)

			pinv_lcv_items = self.lcv_by_pinv_item.get(pinv_i.name, [])
			prec_lcv_items = []
			if pinv_i.purchase_receipt_item:
				prec_lcv_items = self.lcv_by_prec_item.get(pinv_i.purchase_receipt_item, [])

			for lcv_i in pinv_lcv_items + prec_lcv_items:
				for f, tax in zip(self.lcv_amount_fields, self.lcv_account_heads):
					lcv_amount = lcv_i["item_tax_map"].get(tax, {}).get("tax_amount", 0.0)
					pinv_i.setdefault(f, 0.0)
					pinv_i[f] += flt(lcv_amount)

					pinv_i.taxes_in_valuation += flt(lcv_amount)

	def postprocess_row(self, row):
		super().postprocess_row(row)
		row.total_landed_cost = flt(row.base_net_amount) + flt(row.taxes_in_valuation)
		row.landed_cost_rate = flt(row.total_landed_cost) / flt(row.qty) if flt(row.qty) else 0

	def get_tax_columns(self):
		tax_columns = []

		tax_columns.append({
			"label": _("Additional Costs"),
			"fieldname": "taxes_in_valuation",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 120,
		})

		tax_columns.append({
			"label": _("Debit Note Amount"),
			"fieldname": "debit_note_amount",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 120,
		})

		tax_columns.append({
			"label": _("Total Landed Cost"),
			"fieldname": "total_landed_cost",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 120,
		})

		tax_columns.append({
			"label": _("Landed Cost Rate"),
			"fieldname": "landed_cost_rate",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 120,
		})

		tax_columns.append({
			"label": _("Taxes Excl Valuation"),
			"fieldname": "taxes_not_in_valuation",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 120,
		})

		for tax_head, include_in_valuation in self.tax_account_heads:
			amount_field = "tax_" + scrub(tax_head) + "_" + cstr(include_in_valuation)

			label = _(tax_head)
			if include_in_valuation:
				label += " (PINV Cost)"
			else:
				label += " (Not in Valuation)"

			tax_columns.append({
				"label": label,
				"fieldname": amount_field,
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"width": 130
			})

		for lcv_account_head in self.lcv_account_heads:
			amount_field = "lcv_" + scrub(lcv_account_head)
			tax_columns.append({
				"label": _(lcv_account_head) + " (LCV Cost)",
				"fieldname": amount_field,
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"width": 130
			})

		return tax_columns
