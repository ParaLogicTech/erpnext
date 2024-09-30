# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import getdate, today, add_days, cint, combine_datetime
from erpnext.hr.doctype.holiday_list.holiday_list import get_default_holiday_list


def execute(filters=None):
	return VehicleServiceFeedback(filters).run()


class VehicleServiceFeedback:
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})
		self.filters.from_date = getdate(filters.from_date or today())
		self.filters.to_date = getdate(filters.to_date or today())

		if self.filters.from_date > self.filters.to_date:
			frappe.throw(_("Date Range is incorrect"))

	def run(self):
		self.get_data()
		self.process_data()
		self.get_columns()
		return self.columns, self.data

	def get_data(self):
		conditions = self.get_conditions()

		self.filters.feedback_valid_after_service_days = cint(frappe.db.get_value("Vehicles Settings", None, "feedback_valid_after_service_days"))

		if self.filters.date_type == "Feedback Due Date":
			self.filters.date_field = "vgp.posting_date"
			self.filters.from_date = self.subtract_working_days_from_date(self.filters.from_date, self.filters.feedback_valid_after_service_days)
			self.filters.to_date = self.subtract_working_days_from_date(self.filters.to_date, self.filters.feedback_valid_after_service_days)

		elif self.filters.date_type == "Feedback Date":
			self.filters.date_field = "cf.feedback_date"
		else:
			self.filters.date_field = "cf.contact_date"

		self.data = frappe.db.sql("""
			SELECT
				ro.name as project, ro.project_type, ro.project_workshop as workshop, ro.project_name, ro.applies_to_vehicle as vehicle,
				ro.applies_to_item as variant_item_code, ro.applies_to_item_name as variant_item_name, ro.vehicle_license_plate,
				ro.customer, ro.customer_name, ro.contact_mobile, ro.reference_no as reference_ro,
				vgp.posting_date as delivery_date, vgp.posting_time as delivery_time,
				cf.contact_remarks, cf.contact_date, cf.contact_time, cf.customer_feedback, cf.feedback_date, cf.feedback_time
			FROM `tabProject` ro
			LEFT JOIN `tabVehicle Gate Pass` vgp ON vgp.project = ro.name
			LEFT JOIN `tabItem` im ON im.name = ro.applies_to_item
			LEFT JOIN `tabCustomer` c ON c.name = ro.customer
			LEFT JOIN `tabCustomer Feedback` cf ON cf.reference_doctype = 'Project' AND cf.reference_name = ro.name
			WHERE
				{date_field} BETWEEN %(from_date)s AND %(to_date)s
				AND vgp.docstatus = 1
				AND {conditions}
			ORDER BY {date_field}, vgp.creation
		""".format(conditions=conditions, date_field=self.filters.date_field), self.filters, as_dict=1)

	def subtract_working_days_from_date(self, date, no_of_working_days_to_subtract):
		holiday_list_name = get_default_holiday_list(self.filters.company) if self.filters.company else None

		if holiday_list_name:
			holiday_dates = frappe.db.sql_list("""
				select holiday_date from `tabHoliday` where parent=%s and holiday_date<=%s
			""", [holiday_list_name, date])

			if holiday_dates:
				while no_of_working_days_to_subtract:
					date = add_days(date, -1)

					if date not in holiday_dates:
						no_of_working_days_to_subtract -= 1

		return date

	def process_data(self):
		for d in self.data:
			d.feedback_due_date = add_days(d.delivery_date, self.filters.feedback_valid_after_service_days)

			if d.feedback_date:
				d.feedback_dt = combine_datetime(d.feedback_date, d.feedback_time)

			if d.contact_date:
				d.contact_dt = combine_datetime(d.contact_date, d.contact_time)

	def get_conditions(self):
		conditions = []

		if self.filters.get("company"):
			conditions.append("ro.company = %(company)s")

		if self.filters.get("customer"):
			conditions.append("c.name = %(customer)s")

		if self.filters.get("customer_group"):
			lft, rgt = frappe.db.get_value("Customer Group", self.filters.customer_group, ["lft", "rgt"])
			conditions.append("""c.customer_group in (select name from `tabCustomer Group`
				where lft>=%s and rgt<=%s and docstatus<2)""" % (lft, rgt))

		if self.filters.get("variant_of"):
			conditions.append("im.variant_of = %(variant_of)s")

		if self.filters.get("item_code"):
			conditions.append("im.name = %(item_code)s")

		if self.filters.get("item_group"):
			lft, rgt = frappe.db.get_value("Item Group", self.filters.item_group, ["lft", "rgt"])
			conditions.append("""im.item_group in (select name from `tabItem Group`
				where lft>=%s and rgt<=%s and docstatus<2)""" % (lft, rgt))

		conditions.append("""ro.project_type in (select name from `tabProject Type`
			where is_internal != 'Yes')""")
		if self.filters.get("project_type"):
			conditions.append("ro.project_type = %(project_type)s")

		if self.filters.get("project_workshop"):
			conditions.append("ro.project_workshop = %(project_workshop)s")

		if self.filters.get('feedback_filter') == "Submitted Feedback":
			conditions.append("ifnull(cf.customer_feedback, '') != ''")
		elif self.filters.get('feedback_filter') == "Pending Feedback":
			conditions.append("ifnull(cf.customer_feedback, '') = ''")

		if self.filters.get('reference_ro') == "has_reference":
			conditions.append("ifnull(ro.reference_no, '') != ''")
		elif self.filters.get('reference_ro') == "has_no_reference":
			conditions.append("ifnull(ro.reference_no, '') = ''")

		return " AND ".join(conditions) if conditions else ""

	def get_columns(self):
		columns = [
			{
				"label": _("Delivery Date"),
				"fieldname": "delivery_date",
				"fieldtype": "Date",
				"width": 85
			},
			{
				"label": _("Due Date"),
				"fieldname": "feedback_due_date",
				"fieldtype": "Date",
				"width": 85
			},
			{
				'label': _("Project"),
				'fieldname': 'project',
				'fieldtype': 'Link',
				'options': 'Project',
				'width': 100
			},
			{
				'label': _("Reference RO"),
				'fieldname': 'reference_ro',
				'fieldtype': 'Data',
				'width': 130
			},
			{
				'label': _("Project Type"),
				'fieldname': 'project_type',
				'fieldtype': 'Link',
				'options': 'Project Type',
				'width': 140
			},
			{
				'label': _("Workshop"),
				'fieldname': 'workshop',
				'fieldtype': 'Link',
				'options': 'Project Workshop',
				'width': 100
			},
			{
				'label': _("Voice of Customer"),
				'fieldname': 'project_name',
				'fieldtype': 'Data',
				'width': 130
			},
			{
				"label": _("Vehicle"),
				"fieldname": "vehicle",
				"fieldtype": "Link",
				"options": "Vehicle",
				"width": 80
			},
			{
				"label": _("Variant Code"),
				"fieldname": "variant_item_code",
				"fieldtype": "Link",
				"options": "Item",
				"width": 120
			},
			{
				"label": _("Reg No"),
				"fieldname": "vehicle_license_plate",
				"fieldtype": "Data",
				"width": 80
			},
			{
				"label": _("Customer"),
				"fieldname": "customer",
				"fieldtype": "Link",
				"options": "Customer",
				"width": 100
			},
			{
				"label": _("Customer Name"),
				"fieldname": "customer_name",
				"fieldtype": "Data",
				"width": 150
			},
			{
				"label": _("Contact No"),
				"fieldname": "contact_mobile",
				"fieldtype": "Data",
				"width": 100
			},
			{
				"label": _("Contact Date/Time"),
				"fieldname": "contact_dt",
				"fieldtype": "Datetime",
				"width": 150
			},
			{
				"label": _("Contact Remarks"),
				"fieldname": "contact_remarks",
				"fieldtype": "Data",
				"width": 200,
				"editable": 1
			},
			{
				"label": _("Feedback Date/Time"),
				"fieldname": "feedback_dt",
				"fieldtype": "Datetime",
				"width": 150
			},
			{
				"label": _("Customer Feedback"),
				"fieldname": "customer_feedback",
				"fieldtype": "Data",
				"width": 300	,
				"editable": 1
			},
		]
		self.columns = columns
