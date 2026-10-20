# -*- coding: utf-8 -*-
# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cstr
from erpnext.manufacturing.doctype.bom.bom import get_boms_in_bottom_up_order
from frappe.model.document import Document
import click
import json


class BOMUpdateTool(Document):
	def replace_bom(self):
		self.validate_bom()

		self.update_new_bom()
		frappe.cache.delete_key('bom_children')

		new_bom_doc = frappe.get_doc("BOM", self.new_bom)
		new_bom_doc.update_parent_cost()

		bom_list = self.get_parent_boms(self.new_bom)

		with click.progressbar(bom_list) as bom_list:
			pass
		for bom_name in bom_list:
			try:
				parent_bom_doc = frappe.get_doc("BOM", bom_name)
				parent_bom_doc._doc_before_save = parent_bom_doc
				parent_bom_doc.update_exploded_items()
				parent_bom_doc.calculate_cost()
				parent_bom_doc.update_parent_cost()
				parent_bom_doc.db_update()

				if parent_bom_doc.meta.get('track_changes') and not parent_bom_doc.flags.ignore_version:
					parent_bom_doc.save_version()

			except Exception:
				frappe.log_error(title="BOM Replacement Failed", reference_doctype="BOM", reference_name=bom_name)

	def validate_bom(self):
		if not self.current_bom:
			frappe.throw(_("Please select Current BOM"))
		if not self.new_bom:
			frappe.throw(_("Please select New BOM"))

		if cstr(self.current_bom) == cstr(self.new_bom):
			frappe.throw(_("Current BOM and New BOM can not be same"))

		if frappe.db.get_value("BOM", self.current_bom, "item") \
			!= frappe.db.get_value("BOM", self.new_bom, "item"):
				frappe.throw(_("The selected BOMs are not for the same item"))

	def update_new_bom(self):
		frappe.db.sql("""
			update `tabBOM Item`
			set bom_no = %(new_bom)s
			where bom_no = %(current_bom)s
				and docstatus < 2
				and parenttype = 'BOM'
		""", {
			"new_bom": self.new_bom,
			"current_bom": self.current_bom,
		})

	def get_parent_boms(self, bom, bom_list=[]):
		data = frappe.db.sql("""
			SELECT DISTINCT parent
			FROM `tabBOM Item`
			WHERE bom_no = %s AND docstatus < 2 AND parenttype='BOM'
		""", bom)

		for d in data:
			if self.new_bom == d[0]:
				frappe.throw(_("BOM recursion: {0} cannot be child of {1}").format(bom, self.new_bom))

			bom_list.append(d[0])
			self.get_parent_boms(d[0], bom_list)

		return list(set(bom_list))


@frappe.whitelist()
def enqueue_replace_bom(args):
	if isinstance(args, str):
		args = json.loads(args)

	frappe.enqueue("erpnext.manufacturing.doctype.bom_update_tool.bom_update_tool.replace_bom",
		args=args, timeout=40000, queue="long")
	frappe.msgprint(_("Queued for replacing the BOM. It may take a few minutes."))


@frappe.whitelist()
def enqueue_update_cost():
	frappe.enqueue("erpnext.manufacturing.doctype.bom_update_tool.bom_update_tool.update_cost",
		timeout=40000, queue="long")
	frappe.msgprint(_("Queued for updating latest price in all Bill of Materials. It may take a few minutes."))


def update_latest_price_in_all_boms():
	if frappe.db.get_single_value("Manufacturing Settings", "update_bom_costs_automatically"):
		update_cost()


def replace_bom(args):
	args = frappe._dict(args)

	doc = frappe.get_doc("BOM Update Tool")
	doc.current_bom = args.current_bom
	doc.new_bom = args.new_bom
	doc.replace_bom()


def update_cost():
	bom_list = get_boms_in_bottom_up_order()
	for bom in bom_list:
		frappe.get_doc("BOM", bom).update_cost(update_parent=False, from_child_bom=True)
