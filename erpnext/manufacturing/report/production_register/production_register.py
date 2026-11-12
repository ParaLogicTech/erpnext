# Copyright (c) 2026, ParaLogic and contributors
# For license information, please see license.txt

import frappe
from frappe import _, scrub, unscrub
from frappe.utils import cint, cstr, flt, getdate, add_days, combine_datetime
from frappe.desk.query_report import group_report_data
import datetime


def execute(filters=None):
	return ProductionRegister(filters).run()


class ProductionRegister:
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})

	def run(self):
		self.validate_filters()
		self.set_show_names()
		self.set_fieldnames()

		self.get_data()
		self.prepare_data()
		self.get_chart_data()

		grouped_data = self.get_grouped_data()
		self.get_columns()

		return self.columns, grouped_data, None, self.chart_data

	def validate_filters(self):
		self.filters.from_date = getdate(self.filters.from_date)
		self.filters.to_date = getdate(self.filters.to_date)

		self.filters.from_dt = combine_datetime(self.filters.from_date, datetime.time.min)
		self.filters.to_dt = combine_datetime(self.filters.to_date, datetime.time.max)

		if self.filters.from_date > self.filters.to_date:
			frappe.throw(_("Date Range is incorrect"))

	def set_show_names(self):
		self.show_item_name = frappe.defaults.get_global_default('item_naming_by') != "Item Name"
		self.show_customer_name = frappe.defaults.get_global_default('cust_master_name') == "Naming Series"

	def set_fieldnames(self):
		self.qty_fields = ["qty"]

	def get_data(self):
		select_fields, joins = self.get_select_fields_and_joins()
		conditions = self.get_conditions()
		order_by = self.get_order_by()

		select_fields_str = ", ".join(select_fields)
		joins_str = " ".join(joins)
		conditions_str = "and {0}".format(" and ".join(conditions)) if conditions else ""

		self.data = frappe.db.sql(f"""
			select {select_fields_str}
			from `tabWork Order` wo
			{joins_str}
			where wo.docstatus = 1 {conditions_str}
			order by {order_by}
		""", self.filters, as_dict=1)

	def get_select_fields_and_joins(self):
		select_fields = [
			"wo.name as work_order",
			"wo.stock_uom as uom",
			"wo.customer",
			"wo.customer_name",
			"wo.production_item",
			"wo.production_item as item_code",
			"wo.item_name",
			"wo.sales_order",
			"wo.material_request",
		]

		joins = [
			"left join `tabItem` im ON im.name = wo.production_item",
		]

		if self.filters.based_on == "Operation Entry":
			select_fields += [
				"jc.name as job_card",
				"jc.actual_end_dt as posting_dt",
				"date(jc.actual_end_dt) as posting_date",
				"time(jc.actual_end_dt) as posting_time",
				"jc.operation",
				"jc.workstation",
				"jc.total_completed_qty + jc.process_loss_qty as qty",
				"ste.name as stock_entry",
			]

			joins.append("inner join `tabJob Card` jc on jc.work_order = wo.name")
			joins.append("left join `tabStock Entry` ste on ste.job_card = jc.name and ste.purpose = 'Material Consumption for Manufacture' and ste.docstatus = 1")
		else:
			select_fields += [
				"ste.name as stock_entry",
				"ste.posting_date",
				"ste.posting_time",
				"timestamp(ste.posting_date, ste.posting_time) as posting_dt",
				"ste.fg_completed_qty as qty",
			]
			joins.append("inner join `tabStock Entry` ste on ste.work_order = wo.name")

		return select_fields, joins

	def get_order_by(self):
		if self.filters.based_on == "Operation Entry":
			return "jc.actual_end_dt, jc.creation"
		else:
			return "ste.posting_date, ste.posting_time, ste.creation"

	def get_conditions(self):
		conditions = []

		if self.filters.based_on == "Operation Entry":
			conditions.append("jc.docstatus = 1")
			conditions.append("jc.actual_end_dt between %(from_dt)s and %(to_dt)s")
		else:
			conditions.append("ste.docstatus = 1")
			conditions.append("ste.posting_date between %(from_date)s and %(to_date)s")
			conditions.append("ste.purpose = 'Manufacture'")

		if self.filters.company:
			conditions.append("wo.company = %(company)s")

		if self.filters.customer:
			conditions.append("wo.customer = %(customer)s")

		if self.filters.production_item:
			is_template = frappe.db.get_value("Item", self.filters.production_item, 'has_variants')
			if is_template:
				conditions.append("im.variant_of = %(production_item)s")
			else:
				conditions.append("im.name = %(production_item)s")

		if self.filters.item_group:
			lft, rgt = frappe.db.get_value("Item Group", self.filters.item_group, ["lft", "rgt"])
			conditions.append("""im.item_group in (select name from `tabItem Group`
				where lft >= {0} and rgt <= {1})""".format(lft, rgt))

		if self.filters.brand:
			conditions.append("im.brand = %(brand)s")

		if self.filters.item_source:
			conditions.append("im.item_source = %(item_source)s")

		if self.filters.operation:
			if self.filters.based_on == "Operation Entry":
				conditions.append("jc.operation = %(operation)s")
			else:
				conditions.append("""exists(select name from `tabWork Order Operation` woo
					where woo.parent = wo.name and woo.operation = %(operation)s)""")

		if self.filters.workstation:
			if self.filters.based_on == "Operation Entry":
				conditions.append("jc.workstation = %(workstation)s")
			else:
				conditions.append("""exists(select jcc.name from `tabJob Card` jcc
					where jcc.work_order = wo.name and jcc.workstation = %(workstation)s and jcc.docstatus < 2)""")

		if self.filters.get("customer_provided_items"):
			if self.filters.get("customer_provided_items") == "Customer Provided Items Only":
				conditions.append("im.is_customer_provided_item = 1")
			elif self.filters.get("customer_provided_items") == "Exclude Customer Provided Items":
				conditions.append("im.is_customer_provided_item = 0")

		return conditions

	def prepare_data(self):
		for d in self.data:
			d.disable_item_formatter = 1

			if self.filters.based_on == "Operation Entry":
				d.reference_type = "Job Card"
				d.reference = d.job_card
			else:
				d.reference_type = "Stock Entry"
				d.reference = d.stock_entry

	def get_grouped_data(self):
		data = self.data

		if self.filters.based_on == 'Operation Entry':
			self.group_by = ['operation']
		else:
			self.group_by = [None]

		for i in range(3):
			group_label = self.filters.get("group_by_" + str(i + 1), "").replace("Group by ", "")
			if group_label:
				self.group_by.append(scrub(group_label))

		if len(self.group_by) <= 1:
			return data

		return group_report_data(data, self.group_by, calculate_totals=self.calculate_group_totals,
			totals_only=self.filters.totals_only)

	def calculate_group_totals(self, data, group_field, group_value, grouped_by):
		totals = frappe._dict()

		# Copy grouped by into total row
		for f, g in grouped_by.items():
			totals[f] = g

		# Sum
		uoms = set()
		sum_fields = self.qty_fields.copy()
		for d in data:
			for f in sum_fields:
				totals[f] = flt(totals.get(f)) + flt(d.get(f))

			uoms.add(d.uom)

		if len(uoms) == 1:
			totals.uom = list(uoms)[0]

		if data:
			if 'work_order' in grouped_by:
				totals.customer = data[0].get('customer')

		# set reference field
		reference_field = group_field[0] if isinstance(group_field, (list, tuple)) else group_field
		reference_dt = self.fieldname_to_doctype(reference_field)

		totals['reference_type'] = reference_dt
		if not group_field:
			totals['reference'] = "'Total'"
		elif not reference_dt:
			totals['reference'] = "'{0}'".format(grouped_by.get(reference_field))
		else:
			totals['reference'] = grouped_by.get(reference_field)

		if not group_field and self.group_by == [None]:
			totals['reference'] = "'Total'"

		totals['disable_item_formatter'] = cint(self.show_item_name)

		if totals.get('production_item'):
			totals['item_name'] = data[0].item_name

		if totals.get('customer'):
			totals['customer_name'] = data[0].customer_name

		return totals

	def fieldname_to_doctype(self, fieldname):
		group_reference_doctypes = {
			"production_item": "Item",
		}

		return group_reference_doctypes.get(fieldname, unscrub(cstr(fieldname)))

	def get_chart_data(self):
		dates = []
		current_date = self.filters.from_date
		while current_date <= self.filters.to_date:
			dates.append(current_date)
			current_date = add_days(current_date, 1)

		labels = [frappe.format(d) for d in dates]

		if self.filters.based_on == 'Operation Entry':
			operation_totals = {}
			for d in self.data:
				if d.operation:
					operation_totals.setdefault(d.operation, {}).setdefault(d.posting_date, 0)
					operation_totals[d.operation][d.posting_date] += d.qty

			operation_datasets = {}
			for operation, operation_total_dict in operation_totals.items():
				operation_datasets.setdefault(operation, {
					"name": operation, "values": []
				})
				for current_date in dates:
					operation_datasets[operation]["values"].append(flt(operation_total_dict.get(current_date)))

			datasets = list(operation_datasets.values())

		else:
			grand_totals = {}
			for d in self.data:
				grand_totals.setdefault(d.posting_date, 0)
				grand_totals[d.posting_date] += d.qty

			total_dataset = {"name": _("Total Production"), "values": []}
			for current_date in dates:
				total_dataset["values"].append(flt(grand_totals.get(current_date)))

			datasets = [total_dataset]

		self.chart_data = {
			"data": {
				"labels": labels,
				'datasets': datasets
			},
			"colors": ['purple'],
			"type": "line",
			"fieldtype": "Float",
		}

		return self.chart_data

	def get_columns(self):
		columns = [
			{
				"label": _("Date/Time"),
				"fieldname": "posting_dt",
				"fieldtype": "Datetime",
				"width": 90
			},
			{
				"label": _("Item Code"),
				"fieldname": "production_item",
				"fieldtype": "Link",
				"options": "Item",
				"width": 100 if self.show_item_name else 150
			},
			{
				"label": _("Item Name"),
				"fieldname": "item_name",
				"fieldtype": "Data",
				"width": 160
			},
			{
				"label": _("Qty"),
				"fieldname": "qty",
				"fieldtype": "Float",
				"width": 80,
			},
			{
				"label": _("UOM"),
				"fieldname": "uom",
				"fieldtype": "Link",
				"options": "UOM",
				"width": 50,
			},
			{
				"label": _("Operation"),
				"fieldname": "operation",
				"fieldtype": "Link",
				"options": "Operation",
				"width": 90
			},
			{
				"label": _("Workstation"),
				"fieldname": "workstation",
				"fieldtype": "Link",
				"options": "Workstation",
				"width": 90
			},
			{
				"label": _("Work Order"),
				"fieldname": "work_order",
				"fieldtype": "Link",
				"options": "Work Order",
				"width": 100
			},
			{
				"label": _("Job Card"),
				"fieldname": "job_card",
				"fieldtype": "Link",
				"options": "Job Card",
				"width": 100
			},
			{
				"label": _("Stock Entry"),
				"fieldname": "stock_entry",
				"fieldtype": "Link",
				"options": "Stock Entry",
				"width": 120
			},
			{
				"label": _("Sales Order"),
				"fieldname": "sales_order",
				"fieldtype": "Link",
				"options": "Sales Order",
				"width": 100
			},
			{
				"label": _("Material Request"),
				"fieldname": "material_request",
				"fieldtype": "Link",
				"options": "Material Request",
				"width": 110
			},
			{
				"label": _("Customer"),
				"fieldname": "customer",
				"fieldtype": "Link",
				"options": "Customer",
				"width": 80 if self.show_customer_name else 150
			},
			{
				"label": _("Customer Name"),
				"fieldname": "customer_name",
				"fieldtype": "Data",
				"width": 150
			},
		]

		exclude_columns = set()

		if self.filters.based_on != "Operation Entry":
			exclude_columns.add("operation")
			exclude_columns.add("workstation")
			exclude_columns.add("job_card")

		if len(self.group_by) > 1:
			columns.insert(0, {
				"label": _("Reference"),
				"fieldname": "reference",
				"fieldtype": "Dynamic Link",
				"options": "reference_type",
				"width": 200
			})

			if self.filters.totals_only:
				# potential empty columns
				exclude_columns = exclude_columns.union({
					'posting_dt', 'customer', 'customer_name',
					'work_order', 'stock_entry',
					'job_card', 'workstation',
					'sales_order', 'material_request',
					'production_item', 'item_name',
				})

				if "customer" in self.group_by:
					exclude_columns.remove('customer')
					exclude_columns.remove('customer_name')

				if "production_item" in self.group_by:
					exclude_columns.remove('production_item')
					exclude_columns.remove('item_name')

				if "sales_order" in self.group_by:
					exclude_columns.remove('sales_order')
				if "material_request" in self.group_by:
					exclude_columns.remove('material_request')
				if "work_order" in self.group_by:
					exclude_columns.remove('work_order')
				if "workstation" in self.group_by:
					exclude_columns.remove('workstation')

		if not self.show_customer_name:
			exclude_columns.add('customer_name')

		if not self.show_item_name:
			exclude_columns.add('item_name')

		columns = [c for c in columns if c['fieldname'] not in exclude_columns]

		self.columns = columns
