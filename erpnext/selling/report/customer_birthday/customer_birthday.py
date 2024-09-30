# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import today, getdate, format_datetime, add_years
from erpnext.selling.doctype.customer.customer import automated_customer_birthday_enabled, get_customer_birthday_scheduled_time
import datetime


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.from_date = getdate(filters.from_date or today())
	filters.to_date = getdate(filters.to_date or today())

	filters.from_day = filters.from_date.day
	filters.to_day = filters.to_date.day

	filters.from_month = filters.from_date.month
	filters.to_month = filters.to_date.month

	columns = get_columns()
	data = get_data(filters)

	get_notification_data(data)

	return columns, data


def get_data(filters):
	or_conditions = []

	if filters.from_date.year != filters.to_date.year:
		or_conditions.append("""(MONTH(date_of_birth), DAY(date_of_birth)) >= (%(from_month)s, %(from_day)s)
			AND (MONTH(date_of_birth), DAY(date_of_birth)) <= (12, 31)
		""")

		or_conditions.append("""(MONTH(date_of_birth), DAY(date_of_birth)) >= (1, 1)
			AND (MONTH(date_of_birth), DAY(date_of_birth)) <= (%(to_month)s, %(to_day)s)
		""")
	else:
		or_conditions.append("""(MONTH(date_of_birth), DAY(date_of_birth)) >= (%(from_month)s, %(from_day)s)
			AND (MONTH(date_of_birth), DAY(date_of_birth)) <= (%(to_month)s, %(to_day)s)
		""")

	or_conditions = " or ".join(["({0})".format(c) for c in or_conditions])

	data = frappe.db.sql("""
		SELECT
			c.name as customer, c.customer_type, c.customer_name, c.customer_group, c.territory, c.date_of_birth,
			c.mobile_no, c.mobile_no_2, c.phone_no, nc.last_sent_dt, nc.last_scheduled_dt
		FROM `tabCustomer` c
		LEFT JOIN `tabNotification Count` nc
			ON nc.reference_doctype = 'Customer'
			AND nc.reference_name = c.name
			AND nc.notification_type = 'Customer Birthday'
			AND nc.notification_medium = 'SMS'
		WHERE {0}
		ORDER BY MONTH(date_of_birth), DAY(date_of_birth)
	""".format(or_conditions), filters, as_dict=1)

	for d in data:
		d.contact_no = d.mobile_no or d.mobile_no_2 or d.phone_no

	return data


def get_notification_data(data):
	if automated_customer_birthday_enabled():
		datetime_format = "d/MM/y, hh:mm a"
		today_date = getdate()

		for d in data:
			d.notification_date = datetime.date(today_date.year, d.date_of_birth.month, d.date_of_birth.day)
			if d.notification_date < getdate():
				d.notification_date = add_years(d.notification_date, 1)

			birthday_scheduled_dt = get_customer_birthday_scheduled_time(d.notification_date)
			d.birthday_scheduled_dt = birthday_scheduled_dt

			if d.last_sent_dt:
				d.notification = "Last Sent: {0}".format(format_datetime(d.last_sent_dt, datetime_format))
			elif d.birthday_scheduled_dt:
				d.notification = "Scheduled: {0}".format(format_datetime(d.birthday_scheduled_dt, datetime_format))


def get_columns():
	return [
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": "100"
		},
		{
			"fieldname": "customer_name",
			"label": _("Customer Name"),
			"fieldtype": "Data",
			"width": "150"
		},
		{
			"fieldname": "customer_type",
			"label": _("Type"),
			"fieldtype": "Data",
			"width": "100"
		},
		{
			"fieldname": "customer_group",
			"label": _("Customer Group"),
			"fieldtype": "Data",
			"width": "150"
		},
		{
			"fieldname": "territory",
			"label": _("Territory"),
			"fieldtype": "Data",
			"width": "100"
		},
		{
			"fieldname": "date_of_birth",
			"label": _("Date of Birth"),
			"fieldtype": "Date",
			"width": "150"
		},
		{
			"fieldname": "contact_no",
			"label": _("Contact No"),
			"fieldtype": "Data",
			"width": "100"
		},
		{
			"fieldname": "notification",
			"label": _("Notification"),
			"fieldtype": "Data",
			"width": "200"
		},
	]
