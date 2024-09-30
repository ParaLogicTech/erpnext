# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _, scrub
from frappe.utils import getdate, flt, add_to_date, add_days, cstr
from six import iteritems, string_types
from erpnext.accounts.report.financial_statements import get_cost_centers_with_children
from erpnext.accounts.utils import get_fiscal_year
from erpnext import get_default_currency


def execute(filters=None):
	return Analytics(filters).run()


class Analytics(object):
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})
		self.date_field = 'transaction_date' \
			if self.filters.doctype in ['Sales Order', 'Purchase Order'] else 'posting_date'
		self.months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
		self.get_period_date_ranges()
		self.entity_names = {}

		self.filters.party_type = "Customer" if self.filters.doctype in ['Sales Order', 'Delivery Note', 'Sales Invoice']\
			else "Supplier"

	def run(self):
		self.get_columns()
		self.get_data()
		self.get_chart_data()
		return self.columns, self.data, None, self.chart

	def get_columns(self):
		self.columns = [{
			"label": _(self.filters.tree_type),
			"options": self.filters.tree_type,
			"fieldname": "entity",
			"fieldtype": "Link",
			"width": 140
		}]

		show_name = False
		if self.filters.tree_type == "Customer":
			if frappe.defaults.get_global_default('cust_master_name') == "Naming Series":
				show_name = True
		if self.filters.tree_type == "Supplier":
			if frappe.defaults.get_global_default('supp_master_name') == "Naming Series":
				show_name = True
		if self.filters.tree_type == "Item":
			show_name = True

		if show_name:
			self.columns.append({
				"label": _(self.filters.tree_type + " Name"),
				"fieldname": "entity_name",
				"fieldtype": "Data",
				"width": 180
			})

		fieldtype = self.get_value_fieldtype()

		self.columns.append({
			"label": _("Total"),
			"fieldname": "total",
			"fieldtype": fieldtype,
			"width": 120
		})

		for end_date in self.periodic_daterange:
			period = self.get_period(end_date)
			self.columns.append({
				"label": _(period),
				"fieldname": scrub(period),
				"fieldtype": fieldtype,
				"period_column": True,
				"width": 120
			})

	def get_data(self):
		if self.filters.get('company'):
			self.company_currency = frappe.get_cached_value('Company', self.filters.get("company"), "default_currency")
		else:
			self.company_currency = get_default_currency()

		if self.filters.tree_type == 'Customer':
			self.get_entries("s.customer", "s.customer_name")
			self.get_rows()

		if self.filters.tree_type == 'Supplier':
			self.get_entries("s.supplier", "s.supplier_name")
			self.get_rows()

		elif self.filters.tree_type == 'Item':
			self.get_entries("i.item_code", "im.item_name")
			self.get_rows()

		elif self.filters.tree_type == 'Brand':
			self.get_entries("im.brand")
			self.get_rows()

		elif self.filters.tree_type in ["Customer Group", "Supplier Group", "Territory", "Item Group", "Sales Person"]:
			if self.filters.tree_type == 'Customer Group':
				entity_field = "cus.customer_group"
			elif self.filters.tree_type == 'Supplier Group':
				entity_field = "sup.supplier_group"
			elif self.filters.tree_type == 'Territory':
				entity_field = "s.territory"
			elif self.filters.tree_type == 'Item Group':
				entity_field = "im.item_group"
			else:
				entity_field = "sp.sales_person"
			self.get_entries(entity_field)
			self.get_groups()
			self.get_rows_by_group()

	def get_entries(self, entity_field, entity_name_field=None):
		include_sales_person = self.filters.tree_type == "Sales Person" or self.filters.sales_person
		sales_team_join = "left join `tabSales Team` sp on sp.parent = s.name and sp.parenttype = %(doctype)s" \
			if include_sales_person else ""

		party_join = ""
		if self.filters.party_type == "Customer":
			party_join = "inner join `tabCustomer` cus on cus.name = s.customer"
		elif self.filters.party_type == "Supplier":
			party_join = "inner join `tabSupplier` sup on sup.name = s.supplier"

		is_opening_condition = "and s.is_opening != 'Yes'" if self.filters.doctype in ['Sales Invoice', 'Purchase Invoice']\
			else ""

		entity_name_field = "{0} as entity_name, ".format(entity_name_field) if entity_name_field else ""
		if include_sales_person:
			value_field = "i.{} * ifnull(sp.allocated_percentage, 100) / 100".format(self.get_value_fieldname())
		else:
			value_field = "i.{}".format(self.get_value_fieldname())

		self.entries = frappe.db.sql("""
			select
				{entity_field} as entity,
				{entity_name_field}
				{value_field} as value_field,
				s.{date_field}
			from `tab{doctype} Item` i
			inner join `tab{doctype}` s on i.parent = s.name
			left join `tabItem` im on im.name = i.item_code
			{party_join}
			{sales_team_join}
			where s.docstatus = 1
				and s.{date_field} between %(from_date)s and %(to_date)s
				{is_opening_condition} {filter_conditions}
		""".format(
			entity_field=entity_field,
			entity_name_field=entity_name_field,
			value_field=value_field,
			date_field=self.date_field,
			doctype=self.filters.doctype,
			sales_team_join=sales_team_join,
			party_join=party_join,
			is_opening_condition=is_opening_condition,
			filter_conditions=self.get_conditions()
		), self.filters, as_dict=1)

		if entity_name_field:
			for d in self.entries:
				self.entity_names.setdefault(d.entity, d.entity_name)

	def get_value_fieldname(self):
		filter_to_field = {
			"Net Amount": "base_net_amount",
			"Amount": "base_amount",
			"Stock Qty": "stock_qty",
			"Contents Qty": "alt_uom_qty",
			"Transaction Qty": "qty"
		}
		return filter_to_field.get(self.filters.value_field, "base_net_amount")

	def get_value_fieldtype(self):
		filter_to_field = {
			"Net Amount": "Currency",
			"Amount": "Currency",
			"Stock Qty": "Float",
			"Contents Qty": "Float",
			"Transaction Qty": "Float"
		}
		return filter_to_field.get(self.filters.value_field, "Currency")

	def get_conditions(self):
		conditions = []

		if self.filters.get("company"):
			conditions.append("s.company = %(company)s")

		if self.filters.get("customer"):
			conditions.append("s.customer = %(customer)s")

		if self.filters.get("customer_group"):
			lft, rgt = frappe.db.get_value("Customer Group", self.filters.customer_group, ["lft", "rgt"])
			conditions.append("""cus.customer_group in (select name from `tabCustomer Group`
				where lft >= {0} and rgt <= {1})""".format(lft, rgt))

		if self.filters.get("supplier"):
			conditions.append("s.supplier = %(supplier)s")

		if self.filters.get("supplier_group"):
			lft, rgt = frappe.db.get_value("Supplier Group", self.filters.supplier_group, ["lft", "rgt"])
			conditions.append("""sup.supplier_group in (select name from `tabSupplier Group`
				where lft >= {0} and rgt <= {1})""".format(lft, rgt))

		if self.filters.get("item_code"):
			is_template = frappe.db.get_value("Item", self.filters.get('item_code'), 'has_variants')
			if is_template:
				conditions.append("im.variant_of = %(item_code)s")
			else:
				conditions.append("im.name = %(item_code)s")

		if self.filters.get("applies_to_item"):
			is_template = frappe.db.get_value("Item", self.filters.get('applies_to_item'), 'has_variants')
			if is_template:
				self.filters.applies_to_items = [self.filters.applies_to_item]
				self.filters.applies_to_items += [d.name for d in frappe.get_all("Item", {'variant_of': self.filters.applies_to_item})]
				conditions.append("s.applies_to_item in %(applies_to_items)s")
			else:
				conditions.append("s.applies_to_item = %(applies_to_item)s")

		if self.filters.get("item_group"):
			lft, rgt = frappe.db.get_value("Item Group", self.filters.item_group, ["lft", "rgt"])
			conditions.append("""im.item_group in (select name from `tabItem Group`
				where lft >= {0} and rgt <= {1})""".format(lft, rgt))

		if self.filters.get("brand"):
			conditions.append("im.brand = %(brand)s")

		if self.filters.get("item_source"):
			conditions.append("im.item_source = %(item_source)s")

		if self.filters.get("territory"):
			lft, rgt = frappe.db.get_value("Territory", self.filters.territory, ["lft", "rgt"])
			conditions.append("""s.territory in (select name from `tabTerritory`
				where lft >= {0} and rgt <= {1})""".format(lft, rgt))

		if self.filters.get("sales_person"):
			lft, rgt = frappe.db.get_value("Sales Person", self.filters.sales_person, ["lft", "rgt"])
			conditions.append("""sp.sales_person in (select name from `tabSales Person`
				where lft >= {0} and rgt <= {1})""".format(lft, rgt))

		if self.filters.get("order_type"):
			conditions.append("s.order_type = %(order_type)s")

		if self.filters.get("transaction_type"):
			conditions.append("s.transaction_type = %(transaction_type)s")

		if self.filters.get("cost_center"):
			self.filters.cost_center = get_cost_centers_with_children(self.filters.get("cost_center"))

			if frappe.get_meta(self.filters.doctype + " Item").has_field("cost_center") and frappe.get_meta(self.filters.doctype).has_field("cost_center"):
				conditions.append("IF(s.cost_center IS NULL or s.cost_center = '', i.cost_center, s.cost_center) in %(cost_center)s")
			elif frappe.get_meta(self.filters.doctype + " Item").has_field("cost_center"):
				conditions.append("i.cost_center in %(cost_center)s")
			elif frappe.get_meta(self.filters.doctype).has_field("cost_center"):
				conditions.append("s.cost_center in %(cost_center)s")

		if self.filters.get("project"):
			if isinstance(self.filters.project, string_types):
				self.filters.project = cstr(self.filters.get("project")).strip()
				self.filters.project = [d.strip() for d in self.filters.project.split(',') if d]

			if frappe.get_meta(self.filters.doctype + " Item").has_field("project") and frappe.get_meta(self.filters.doctype).has_field("project"):
				conditions.append("IF(i.project IS NULL or i.project = '', s.project, i.project) in %(project)s")
			elif frappe.get_meta(self.filters.doctype + " Item").has_field("project"):
				conditions.append("i.project in %(project)s")
			elif frappe.get_meta(self.filters.doctype).has_field("project"):
				conditions.append("s.project in %(project)s")

		if self.filters.get("warehouse"):
			lft, rgt = frappe.db.get_value("Warehouse", self.filters.warehouse, ["lft", "rgt"])
			conditions.append("""i.warehouse in (select name from `tabWarehouse`
				where lft >= {0} and rgt <= {1})""".format(lft, rgt))

		return "and {}".format(" and ".join(conditions)) if conditions else ""

	def get_rows(self):
		self.data = []
		self.get_periodic_data()

		total_row = frappe._dict({"entity": _("'Total'"), "total": 0})
		self.data.append(total_row)

		for entity, period_data in iteritems(self.entity_periodic_data):
			row = {
				"entity": entity,
				"entity_name": self.entity_names.get(entity),
				"indent": 1
			}
			total = 0
			for end_date in self.periodic_daterange:
				period = self.get_period(end_date)
				amount = flt(period_data.get(period, 0.0))
				row[scrub(period)] = amount
				total += amount

				total_row.setdefault(scrub(period), 0.0)
				total_row[scrub(period)] += amount
				total_row["total"] += amount

			row["total"] = total

			if self.filters.tree_type == "Item":
				row["stock_uom"] = period_data.get("stock_uom")

			self.data.append(row)

	def get_rows_by_group(self):
		self.get_periodic_data()
		out = []

		for d in reversed(self.group_entries):
			row = {
				"entity": d.name,
				"indent": self.depth_map.get(d.name)
			}
			total = 0
			for end_date in self.periodic_daterange:
				period = self.get_period(end_date)
				amount = flt(self.entity_periodic_data.get(d.name, {}).get(period, 0.0))
				row[scrub(period)] = amount
				if d.parent and (self.filters.tree_type != "Order Type" or d.parent == "Order Types"):
					self.entity_periodic_data.setdefault(d.parent, frappe._dict()).setdefault(period, 0.0)
					self.entity_periodic_data[d.parent][period] += amount
				total += amount
			row["total"] = total
			out = [row] + out
		self.data = out

	def get_periodic_data(self):
		self.entity_periodic_data = frappe._dict()

		for d in self.entries:
			period = self.get_period(d.get(self.date_field))
			self.entity_periodic_data.setdefault(d.entity, frappe._dict()).setdefault(period, 0.0)
			self.entity_periodic_data[d.entity][period] += flt(d.value_field)

			if self.filters.tree_type == "Item":
				self.entity_periodic_data[d.entity]['stock_uom'] = d.stock_uom

	def get_period(self, posting_date):
		if self.filters.range == 'Weekly':
			period = "Week " + str(posting_date.isocalendar()[1]) + " " + str(posting_date.year)
		elif self.filters.range == 'Monthly':
			period = str(self.months[posting_date.month - 1]) + " " + str(posting_date.year)
		elif self.filters.range == 'Quarterly':
			period = "Quarter " + str(((posting_date.month - 1) // 3) + 1) + " " + str(posting_date.year)
		else:
			year = get_fiscal_year(posting_date, company=self.filters.company)
			period = str(year[0])
		return period

	def get_period_date_ranges(self):
		from dateutil.relativedelta import relativedelta, MO
		from_date, to_date = getdate(self.filters.from_date), getdate(self.filters.to_date)

		increment = {
			"Monthly": 1,
			"Quarterly": 3,
			"Half-Yearly": 6,
			"Yearly": 12
		}.get(self.filters.range, 1)

		if self.filters.range in ['Monthly', 'Quarterly']:
			from_date = from_date.replace(day=1)
		elif self.filters.range == "Yearly":
			from_date = get_fiscal_year(from_date)[1]
		else:
			from_date = from_date + relativedelta(from_date, weekday=MO(-1))

		self.periodic_daterange = []
		for dummy in range(1, 53):
			if self.filters.range == "Weekly":
				period_end_date = add_days(from_date, 6)
			else:
				period_end_date = add_to_date(from_date, months=increment, days=-1)

			if period_end_date > to_date:
				period_end_date = to_date

			self.periodic_daterange.append(period_end_date)

			from_date = add_days(period_end_date, 1)
			if period_end_date == to_date:
				break

	def get_groups(self):
		if self.filters.tree_type == "Territory":
			parent = 'parent_territory'
		if self.filters.tree_type == "Customer Group":
			parent = 'parent_customer_group'
		if self.filters.tree_type == "Item Group":
			parent = 'parent_item_group'
		if self.filters.tree_type == "Supplier Group":
			parent = 'parent_supplier_group'
		if self.filters.tree_type == "Sales Person":
			parent = 'parent_sales_person'

		self.depth_map = frappe._dict()

		self.group_entries = frappe.db.sql("""select name, lft, rgt , {parent} as parent
			from `tab{tree}` order by lft"""
		.format(tree=self.filters.tree_type, parent=parent), as_dict=1)

		for d in self.group_entries:
			if d.parent:
				self.depth_map.setdefault(d.name, self.depth_map.get(d.parent) + 1)
			else:
				self.depth_map.setdefault(d.name, 0)

	def get_chart_data(self):
		labels = [d.get("label") for d in self.columns if d.get("period_column")]
		self.chart = {
			"data": {
				'labels': labels,
				'datasets': []
			},
			"type": "line",
			"fieldtype": self.get_value_fieldtype()
		}

		if self.chart.get("fieldtype") == "Currency":
			self.chart['options'] = self.company_currency
