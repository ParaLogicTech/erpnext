import frappe
from frappe import _
from frappe.utils import flt, cint, getdate


def execute(filters=None):
	return GoodsInTransitTracker(filters).run()


class GoodsInTransitTracker:
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or dict())
		self.show_item_name = frappe.defaults.get_global_default('item_naming_by') != "Item Name"
		self.has_branch = False
		self.has_project = False

	def run(self):
		self.get_data()
		self.prepare_data()
		columns = self.get_columns()

		return columns, self.data

	def get_data(self):
		conditions = self.get_conditions()
		qty_field = self.get_qty_fieldname()

		self.data = frappe.db.sql(f"""
			select
				o.name as stock_entry,
				o.company,
				o.posting_date,
				o.project as parent_project,
				i.project as item_project,
				i.item_code,
				i.item_name,
				i.s_warehouse as from_warehouse,
				o.to_warehouse,
				o.branch,
				i.{qty_field} as qty,
				i.transferred_qty,
				i.uom,
				i.stock_uom,
				i.alt_uom,
				i.conversion_factor,
				i.alt_uom_size,
				im.brand,
				im.item_group
			from `tabStock Entry Detail` i
			inner join `tabStock Entry` o on o.name = i.parent
			inner join `tabItem` im on im.name = i.item_code
			where
				o.docstatus = 1
				and o.purpose = 'Send to Warehouse'
				and o.transfer_status = 'In Transit'
				and i.transferred_qty < i.qty
				{conditions}
			order by o.posting_date, o.posting_time, o.creation, i.idx
		""", self.filters, as_dict=1)

	def get_conditions(self):
		conditions = []

		if self.filters.company:
			conditions.append("o.company = %(company)s")

		if self.filters.branch:
			conditions.append("o.branch = %(branch)s")

		if self.filters.item_code:
			if frappe.db.get_value("Item", self.filters.item_code, 'has_variants'):
				conditions.append("im.variant_of = %(item_code)s")
			else:
				conditions.append("i.item_code = %(item_code)s")

		if self.filters.item_group:
			lft, rgt = frappe.db.get_value("Item Group", self.filters.item_group, ["lft", "rgt"])
			conditions.append("""im.item_group IN (SELECT name FROM `tabItem Group`
				WHERE lft >= {0} AND rgt <= {1})""".format(lft, rgt))

		if self.filters.brand:
			conditions.append("im.brand = %(brand)s")

		if self.filters.item_source:
			conditions.append("im.item_source = %(item_source)s")

		if self.filters.get("project"):
			if isinstance(self.filters.project, str):
				self.filters.project = [self.filters.project]

			if frappe.get_meta(self.filters.doctype + " Item").has_field("project") and frappe.get_meta(self.filters.doctype).has_field("project"):
				conditions.append("(i.project in %(project)s or ((i.project IS NULL or i.project = '') and o.project in %(project)s))")
			elif frappe.get_meta(self.filters.doctype + " Item").has_field("project"):
				conditions.append("i.project in %(project)s")
			elif frappe.get_meta(self.filters.doctype).has_field("project"):
				conditions.append("o.project in %(project)s")

		if self.filters.get("from_warehouse"):
			lft, rgt = frappe.db.get_value("Warehouse", self.filters.from_warehouse, ["lft", "rgt"])
			conditions.append("""i.s_warehouse in (select name from `tabWarehouse`
				where lft >= {0} and rgt <= {1})""".format(lft, rgt))

		if self.filters.get("to_warehouse"):
			lft, rgt = frappe.db.get_value("Warehouse", self.filters.to_warehouse, ["lft", "rgt"])
			conditions.append("""o.to_warehouse in (select name from `tabWarehouse`
				where lft >= {0} and rgt <= {1})""".format(lft, rgt))

		return "AND {0}".format(" AND ".join(conditions)) if conditions else ""

	def prepare_data(self):
		today_date = getdate()

		for d in self.data:
			# Set UOM based on qty field
			if self.filters.qty_field == "Contents Qty":
				d.uom = d.alt_uom or d.stock_uom
				d.transferred_qty = d.transferred_qty * d.conversion_factor * d.alt_uom_size
			elif self.filters.qty_field == "Stock Qty":
				d.uom = d.stock_uom
				d.transferred_qty = d.transferred_qty * d.conversion_factor

			d["remaining_qty"] = d["qty"] - d["transferred_qty"]

			d["delay_days"] = max((today_date - getdate(d["posting_date"])).days, 0)

			d["disable_item_formatter"] = cint(self.show_item_name)

			if d.get("project"):
				self.has_project = True
			if d.get("branch"):
				self.has_branch = True

	def get_qty_fieldname(self):
		filter_to_field = {
			"Stock Qty": "stock_qty",
			"Contents Qty": "alt_uom_qty",
			"Transaction Qty": "qty"
		}
		return filter_to_field.get(self.filters.qty_field) or "stock_qty"

	def get_columns(self):
		columns = [
			{
				"label": _("Out Date"),
				"fieldname": "posting_date",
				"fieldtype": "Date",
				"width": 80
			},
			{
				"label": _("Outgoing Entry"),
				"fieldname": "stock_entry",
				"fieldtype": "Link",
				"options": "Stock Entry",
				"width": 140
			},
			{
				"label": _("Item Code"),
				"fieldname": "item_code",
				"fieldtype": "Link",
				"options": "Item",
				"width": 100 if self.show_item_name else 150
			},
			{
				"label": _("Item Name"),
				"fieldname": "item_name",
				"fieldtype": "Data",
				"width": 150
			},
			{
				"label": _("From Warehouse"),
				"fieldname": "from_warehouse",
				"fieldtype": "Link",
				"options": "Warehouse",
				"width": 150
			},
			{
				"label": _("To Warehouse"),
				"fieldname": "to_warehouse",
				"fieldtype": "Link",
				"options": "Warehouse",
				"width": 150
			},
			{
				"label": _("UOM"),
				"fieldtype": "Link",
				"options": "UOM",
				"fieldname": "uom",
				"width": 50
			},
			{
				"label": _("Sent"),
				"fieldname": "qty",
				"fieldtype": "Float",
				"width": 80
			},
			{
				"label": _("Received"),
				"fieldname": "transferred_qty",
				"fieldtype": "Float",
				"width": 80
			},
			{
				"label": _("In Transit"),
				"fieldname": "remaining_qty",
				"fieldtype": "Float",
				"width": 80
			},
			{
				"label": _("Delay Days"),
				"fieldname": "delay_days",
				"fieldtype": "Int",
				"width": 80
			},
			{
				"label": _("Project"),
				"fieldname": "project",
				"fieldtype": "Link",
				"options": "Project",
				"width": 100
			},
			{
				"label": _("Branch"),
				"fieldname": "branch",
				"fieldtype": "Link",
				"options": "Branch",
				"width": 100
			},
			{
				"label": _("Item Group"),
				"fieldname": "item_group",
				"fieldtype": "Link",
				"options": "Item Group",
				"width": 90
			},
			{
				"label": _("Brand"),
				"fieldname": "brand",
				"fieldtype": "Link",
				"options": "Brand",
				"width": 60
			},
		]

		if not self.show_item_name:
			columns = [c for c in columns if c['fieldname'] != 'item_name']

		if not self.has_project:
			columns = [c for c in columns if c['fieldname'] != 'project']
		if not self.has_branch:
			columns = [c for c in columns if c['fieldname'] != 'branch']

		return columns
