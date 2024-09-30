# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe	import _
from erpnext.stock.report.stock_ledger.stock_ledger import get_item_details


def execute(filters=None):
	return StockTraceReport(filters).run()


class StockTraceReport:
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})
		self.show_item_name = frappe.defaults.get_global_default('item_naming_by') != "Item Name"
		self.item_codes = set()

	def run(self):
		self.validate_filters()
		self.sles = self.get_batch_ledger_entries(self.filters.batch_no)
		self.get_item_details()
		rows = self.prepare_rows()
		columns = self.get_columns()

		return columns, rows

	def validate_filters(self):
		if not self.filters.batch_no:
			frappe.throw(_("Please select either Batch No or Serial No"))

	def get_batch_ledger_entries(self, batch_no, incoming_only=False):
		sles = self._get_sles("sle.batch_no = %(batch_no)s", {
			"batch_no": batch_no
		})
		self.get_dependent_sles(sles)

		if incoming_only:
			sles = [d for d in sles if d.actual_qty > 0 and d.purpose not in ("Material Transfer for Manufacture", "Material Transfer")]

		return sles

	def get_dependent_sles(self, parent_sles):
		dependency_map = self.get_sle_dependency_map(parent_sles)
		source_sle_names = [d.name for d in parent_sles]

		for parent_sle in parent_sles:
			dependency_keys = dependency_map.get(parent_sle.name)
			if not dependency_map.get(parent_sle.name):
				continue

			conditions = """
				(sle.voucher_type, sle.voucher_no, sle.voucher_detail_no) in %(dependency_keys)s
				and sle.name not in %(source_sle_names)s
			"""

			parent_sle.dependent_sles = self._get_sles(conditions, {
				"dependency_keys": dependency_keys,
				"source_sle_names": source_sle_names,
			})

			for child_sle in parent_sle.dependent_sles:
				if not child_sle.batch_no:
					continue

				child_sle.dependent_sles = self.get_batch_ledger_entries(child_sle.batch_no, incoming_only=True)

	def get_sle_dependency_map(self, sles):
		names = [d.name for d in sles]
		if not names:
			return []

		dependencies = frappe.db.sql("""
			select parent, dependent_voucher_type, dependent_voucher_no, dependent_voucher_detail_no
			from `tabStock Ledger Entry Dependency`
			where parent in %s
		""", [names], as_dict=1)

		dependency_map = {}
		for d in dependencies:
			dependency_key = (d.dependent_voucher_type, d.dependent_voucher_no, d.dependent_voucher_detail_no)
			dependency_map.setdefault(d.parent, []).append(dependency_key)

		return dependency_map

	def _get_sles(self, conditions, values):
		if isinstance(conditions, str):
			conditions = [conditions]

		conditions = " and ".join(conditions)

		sles = frappe.db.sql(f"""
			select sle.name, sle.voucher_detail_no,
				sle.item_code, sle.warehouse, sle.batch_no, sle.packing_slip, sle.serial_no, sle.company,
				sle.actual_qty, sle.incoming_rate, sle.stock_value_difference,
				sle.voucher_type, sle.voucher_no, ste.purpose,
				sle.party_type, sle.party, sle.project,
				sle.posting_date, sle.posting_time, timestamp(sle.posting_date, sle.posting_time) as posting_dt
			from `tabStock Ledger Entry` sle
			left join `tabStock Entry` ste on ste.name = sle.voucher_no and sle.voucher_type = 'Stock Entry'
			where {conditions}
			order by sle.posting_date, sle.posting_time, sle.creation
		""", values, as_dict=1)

		for sle in sles:
			self.item_codes.add(sle.item_code)

		return sles

	def get_item_details(self):
		self.item_details = get_item_details(list(self.item_codes))

	def prepare_rows(self):
		rows = []

		for sle in self.sles:
			self.add_row(sle, rows)

		return rows

	def add_row(self, parent_sle, rows):
		if parent_sle.get("dependent_sles"):
			self.prepare_sle(parent_sle)
			group = self.get_group_object(parent_sle)
			for child_sle in parent_sle.dependent_sles:
				self.add_row(child_sle, group.rows)

			rows.append(group)
		else:
			self.prepare_sle(parent_sle)
			rows.append(parent_sle)

	def get_group_object(self, sle):
		sle._bold = 1
		return frappe._dict({
			"_isGroup": 1,
			"rows": [],
			"totals": sle,
		})

	def prepare_sle(self, sle):
		item_details = self.item_details.get(sle.item_code) or frappe._dict()

		sle.item_name = item_details.item_name
		sle.uom = item_details.stock_uom
		sle.disable_item_formatter = 1

	def get_columns(self):
		columns = [
			{"label": _("Batch"), "fieldname": "batch_no", "fieldtype": "Link", "options": "Batch", "width": 250, "is_batch": 1},
			{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 100 if self.show_item_name else 150},
			{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 150},
			{"label": _("Voucher Type"), "fieldname": "voucher_type", "width": 110},
			{"label": _("Voucher #"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 120},
			{"label": _("Date"), "fieldname": "posting_dt", "fieldtype": "Datetime", "width": 95},
			{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 100},
			{"label": _("Qty"), "fieldname": "actual_qty", "fieldtype": "Float", "width": 90, "convertible": "qty"},
			{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Link", "options": "UOM", "width": 50},
			{"label": _("Purpose"), "fieldname": "purpose", "fieldtype": "Data", "width": 110},
			{"label": _("Package"), "fieldname": "packing_slip", "fieldtype": "Link", "options": "Packing Slip", "width": 95, "is_packing_slip": 1},
		]

		columns += [
			{"label": _("Party Type"), "fieldname": "party_type", "fieldtype": "Data", "width": 70},
			{"label": _("Party"), "fieldname": "party", "fieldtype": "Dynamic Link", "options": "party_type", "width": 150},
			{"label": _("Serial #"), "fieldname": "serial_no", "fieldtype": "Link", "options": "Serial No", "width": 100},
			{"label": _("Project"), "fieldname": "project", "fieldtype": "Link", "options": "Project", "width": 100},
		]

		return columns
