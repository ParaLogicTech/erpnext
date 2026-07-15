# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from erpnext.utilities.transaction_base import TransactionBase
from dateutil.relativedelta import relativedelta
from frappe.utils import add_days, getdate, get_time, now_datetime, combine_datetime, add_to_date, cstr, cint
from erpnext.accounts.party import _get_contact_details
from crm.crm.utils import get_primary_contact
from frappe.model.document import Document
from frappe.core.doctype.notification_count.notification_count import (
	get_notification_last_scheduled,
	set_notification_last_scheduled,
)


class MaintenanceSchedule(TransactionBase):
	def validate(self):
		self.set_missing_values()
		self.validate_serial_no()
		self.validate_schedule()

	def set_missing_values(self):
		self.set_contact_details()

	def set_contact_details(self):
		force = False
		if not self.contact_person and self.customer:
			contact = get_primary_contact('Customer', self.customer)
			self.contact_person = contact
			force = True

		if self.contact_person:
			contact_details = _get_contact_details(self.contact_person)
			for k, v in contact_details.items():
				if self.meta.has_field(k) and (force or not self.get(k)):
					self.set(k, v)

	def validate_serial_no(self):
		if self.serial_no:
			self.item_code, self.item_name = frappe.db.get_value("Serial No", self.serial_no, ["item_code", "item_name"])

	def validate_schedule(self):
		self.sort_schedules()
		date_template_pairs = set()

		for d in self.schedules:
			date_template_pair = (d.scheduled_date, cstr(d.service_type), cstr(d.service_template))
			if date_template_pair not in date_template_pairs:
				date_template_pairs.add(date_template_pair)
			else:
				frappe.throw(_("Row {0}: Duplicate schedule found".format(d.idx)))

	def sort_schedules(self):
		self.schedules.sort(key=lambda x: x.get('scheduled_date'))
		for index, d in enumerate(self.schedules):
			d.idx = index + 1

	def adjust_scheduled_date_for_holiday(self, scheduled_date):
		from erpnext.hr.doctype.holiday_list.holiday_list import get_default_holiday_list, adjust_date_for_holidays

		holiday_list = frappe.get_cached_value("Projects Settings", None, "maintenance_schedule_holiday_list")
		if not holiday_list:
			holiday_list = get_default_holiday_list(self.company)

		return adjust_date_for_holidays(scheduled_date, holiday_list)

	def send_maintenance_schedule_reminder_notification(self, row_name):
		ms_row = [d for d in self.schedules if d.name == row_name]
		if not ms_row:
			return

		ms_row = ms_row[0]
		context = frappe._dict({"row": ms_row, "child_doctype": "Maintenance Schedule Detail", "child_name": row_name})
		self.run_method("notify_maintenance_reminder", context=context)

	def trigger_maintenance_schedule_opportunity(self, row_name):
		ms_row = [d for d in self.schedules if d.name == row_name]
		if not ms_row:
			return

		ms_row = ms_row[0]

		opportunity = None
		if cint(frappe.db.get_single_value("Projects Settings", "auto_create_opportunity_from_schedule")):
			opportunity = self.create_maintenance_opportunity(row_name)

		context = frappe._dict({
			"row": ms_row,
			"child_doctype": "Maintenance Schedule Detail",
			"child_name": row_name,
			"opportunity": opportunity,
		})
		self.run_method("notify_maintenance_opportunity", context=context)

	def validate_notification(self, notification_type=None, child_doctype=None, child_name=None, throw=False):
		if notification_type in ("Maintenance Reminder",):
			ms_row = [d for d in self.schedules if d.name == child_name]
			if not ms_row:
				frappe.throw(_("Invalid Maintenance Schedule"))
			ms_row = ms_row[0]

			if not ms_row.scheduled_date:
				if throw:
					frappe.throw(_("Scheduled Date not found"))
				return False

			if getdate(ms_row.scheduled_date) < getdate():
				if throw:
					frappe.throw(_("Cannot send {0} notification after Scheduled Date has passed")
						.format(notification_type))
				return False

			if self.status != "Active":
				if throw:
					frappe.throw(_("Cannot send {0} notification because Maintenance Schedule status is not 'Active'")
						.format(notification_type))
				return False
		return True

	def create_maintenance_opportunity(self, row_name):
		opportunity_doc = make_maintenance_opportunity(self, row_name)
		opportunity_doc.flags.ignore_mandatory = True
		opportunity_doc.save(ignore_permissions=True)
		return opportunity_doc


def auto_schedule_next_service_templates():
	if not frappe.db.get_single_value("Projects Settings", "auto_schedule_next_service_templates"):
		return

	run_date = getdate()
	schedule_date = add_to_date(date=run_date, days=-1)

	schedule_data = frappe.db.sql("""
		select msd.service_template, ms.serial_no
		from `tabMaintenance Schedule Detail` msd
		inner join `tabMaintenance Schedule` ms on ms.name = msd.parent
		inner join `tabService Template` pt on pt.name = msd.service_template
		where
			msd.scheduled_date = %s
			and msd.service_type = 'Maintenance'
			and ms.status = 'Active'
			and ifnull(ms.serial_no, '') != ''
			and ifnull(pt.next_service_template, '') != ''
	""", schedule_date, as_dict=1)

	for schedule in schedule_data:
		schedule_next_service_template(
			schedule.service_template,
			schedule.serial_no,
			service_type="Maintenance",
			args={"reference_date": schedule_date},
			overwrite_existing=False
		)


def schedule_next_service_template(
	service_template,
	serial_no,
	service_type="Maintenance",
	args=None,
	overwrite_existing=True,
):
	if not service_template:
		return

	args = frappe._dict(args or {})

	template_details = frappe.get_cached_value("Service Template", service_template, ["next_due_after", "next_service_template"], as_dict=1)
	if not template_details or not template_details.next_due_after or not template_details.next_service_template:
		return

	service_type = service_type or "Maintenance"

	doc = get_maintenance_schedule_doc(serial_no)

	schedule = frappe._dict({
		'service_template': template_details.next_service_template,
		'service_type': service_type,
		'reference_doctype': args.reference_doctype,
		'reference_name': args.reference_name,
		'reference_date': getdate(args.reference_date)
	})
	schedule.scheduled_date = schedule.reference_date + relativedelta(months=template_details.next_due_after)

	remind_days_before = cint(frappe.get_cached_value("Projects Settings", None, "maintenance_reminder_days_before"))
	future_reference_date = add_days(schedule.reference_date, remind_days_before)
	future_rows = [d for d in doc.get('schedules') if getdate(d.scheduled_date) > future_reference_date]

	if service_type == "Maintenance":
		existing_row = [d for d in doc.get('schedules') if (
			d.reference_doctype == schedule.reference_doctype
			and d.reference_name == schedule.reference_name
			and d.service_type == "Maintenance"
		)]
		if not existing_row:
			existing_row = [d for d in future_rows if d.service_type == "Maintenance"]
	else:
		existing_row = [d for d in doc.get('schedules') if (
			d.reference_doctype == schedule.reference_doctype
			and d.reference_name == schedule.reference_name
			and d.service_template == template_details.next_service_template
		)]
		if not existing_row:
			existing_row = [d for d in future_rows if d.service_template == template_details.next_service_template]

	existing_row = existing_row[0] if existing_row else None
	if existing_row and not overwrite_existing:
		return

	schedule.scheduled_date = doc.adjust_scheduled_date_for_holiday(schedule.scheduled_date)
	if existing_row:
		existing_row.update(schedule)
	else:
		doc.append('schedules', schedule)

	update_customer_and_contact(args, doc)
	doc.save(ignore_permissions=True)


def schedule_service_templates_after_delivery(serial_no, args):
	item_code = frappe.db.get_value("Serial No", serial_no, "item_code")
	if not item_code:
		return

	args = frappe._dict(args)
	if not args.reference_doctype or not args.reference_name:
		frappe.throw(_("Invalid reference for Maintenance Schedule after Delivery"))

	schedule_template = frappe._dict({
		'reference_doctype': args.reference_doctype,
		'reference_name': args.reference_name,
		'reference_date': getdate(args.reference_date),
		'service_type': 'Maintenance',
	})

	service_templates = get_service_templates_due_after_delivery(item_code)

	doc = get_maintenance_schedule_doc(serial_no)
	modified = False

	update_customer_and_contact(args, doc)

	existing_templates = [d.get('service_template') for d in doc.get('schedules', []) if d.get('service_template')]

	for d in service_templates:
		if d.name not in existing_templates:
			schedule = schedule_template.copy()
			schedule.service_template = d.name
			schedule.scheduled_date = schedule.reference_date + relativedelta(months=d.due_after_delivery_date)
			schedule.scheduled_date = doc.adjust_scheduled_date_for_holiday(schedule.scheduled_date)
			doc.append('schedules', schedule)

			modified = True

	if modified:
		doc.save(ignore_permissions=True)


def remove_schedule_for_reference_document(serial_no, reference_doctype, reference_name):
	doc = get_maintenance_schedule_doc(serial_no)

	if not doc.get('schedules'):
		return

	to_remove = [d for d in doc.schedules if d.reference_doctype == reference_doctype and d.reference_name == reference_name]
	if to_remove:
		for d in to_remove:
			doc.remove(d)

		doc.save(ignore_permissions=True)


def get_service_templates_due_after_delivery(item_code):
	filters = {'due_after_delivery_date': ['>', 0]}

	fields = ['name', 'due_after_delivery_date']
	order_by = "due_after_delivery_date"

	filters['applies_to_item'] = item_code
	service_templates = frappe.get_all('Service Template', filters=filters, fields=fields, order_by=order_by)

	if not service_templates:
		variant_of = frappe.get_cached_value("Item", item_code, "variant_of")
		if variant_of:
			filters["applies_to_item"] = variant_of
			service_templates = frappe.get_all('Service Template', filters=filters, fields=fields, order_by=order_by)

	return service_templates


def get_maintenance_schedule_doc(serial_no):
	schedule_name = frappe.db.get_value('Maintenance Schedule', filters={'serial_no': serial_no})

	if schedule_name:
		doc = frappe.get_doc('Maintenance Schedule', schedule_name)
	else:
		doc = frappe.new_doc('Maintenance Schedule')
		doc.serial_no = serial_no
		doc.item_code, doc.item_name = frappe.db.get_value("Serial No", serial_no, ["item_code", "item_name"])

	return doc


def update_customer_and_contact(source, target_doc):
	customer_fields = ['customer', 'customer_name']
	contact_fields = ['contact_person', 'contact_display', 'contact_mobile', 'contact_phone', 'contact_email']

	if source.customer:
		for f in customer_fields:
			target_doc.set(f, source.get(f))

		for f in contact_fields:
			target_doc.set(f, None)

	if source.contact_person:
		for f in contact_fields:
			target_doc.set(f, source.get(f))


def get_maintenance_schedule_from_serial_no(serial_no):
	schedule_name = frappe.db.get_value('Maintenance Schedule', filters={'serial_no': serial_no})

	if schedule_name:
		schedule_doc = frappe.get_doc('Maintenance Schedule', schedule_name)
		return schedule_doc.schedules


def trigger_maintenance_schedule_opportunities(for_date=None):
	if automated_maintenance_opportunity_enabled():
		return

	schedules_to_process = get_maintenance_schedules_for_opportunity_creation(for_date)
	for d in schedules_to_process:
		try:
			doc = frappe.get_doc("Maintenance Schedule", d.ms_name)
			doc.trigger_maintenance_schedule_opportunity(d.row_name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title="Error Triggering Maintenance Schedule Opportunity",
				reference_doctype="Maintenance Schedule",
				reference_name=d.ms_name,
			)
			frappe.db.commit()


def get_maintenance_schedule_opportunity(maintenance_schedule, row):
	maintenance_opp = frappe.db.get_value("Opportunity", filters={
		'maintenance_schedule': maintenance_schedule,
		'maintenance_schedule_row': row
	})

	if maintenance_opp:
		return frappe.get_doc('Opportunity', maintenance_opp)
	else:
		return make_maintenance_opportunity(maintenance_schedule, row)


@frappe.whitelist()
def make_maintenance_opportunity(maintenance_schedule, row):
	if isinstance(maintenance_schedule, Document):
		schedule_doc = maintenance_schedule
	else:
		schedule_doc = frappe.get_doc('Maintenance Schedule', maintenance_schedule)

	schedule = schedule_doc.getone('schedules', {'name': row})
	if not schedule:
		frappe.throw(_("Invalid Maintenance Schedule Row Provided"))

	default_opportunity_type = frappe.get_cached_value("Projects Settings", None, "default_opportunity_type_for_schedule")

	target_doc = frappe.new_doc('Opportunity')

	target_doc.opportunity_from = 'Customer'
	target_doc.party_name = schedule_doc.customer
	target_doc.transaction_date = getdate()
	target_doc.due_date = schedule.scheduled_date
	target_doc.status = 'Open'
	target_doc.opportunity_type = default_opportunity_type
	target_doc.applies_to_serial_no = schedule_doc.serial_no

	target_doc.maintenance_schedule = schedule_doc.name
	target_doc.maintenance_schedule_row = schedule.name

	# if schedule.service_template:
	# 	service_template = frappe.get_cached_doc('Service Template', schedule.service_template)
	# 	for d in service_template.sales_items:
	# 		target_doc.append("items", {
	# 			"item_code": d.applicable_item_code,
	# 			"qty": d.applicable_qty,
	# 		})

	target_doc.run_method("set_missing_values")
	target_doc.run_method("validate_maintenance_schedule")
	return target_doc


def send_maintenance_schedule_reminder_notifications():
	if not automated_maintenance_reminder_enabled():
		return

	now_dt = now_datetime()
	reminder_date = getdate(now_dt)
	reminder_dt = get_maintenance_reminder_scheduled_time(reminder_date)
	if now_dt < reminder_dt:
		return

	last_scheduled = get_notification_last_scheduled(
		"Maintenance Schedule",
		"",
		"Maintenance Reminder",
		"",
	)
	if last_scheduled and getdate(last_scheduled) >= reminder_date:
		return

	schedules_to_remind = get_maintenance_schedules_for_reminder_notification(reminder_date)

	for d in schedules_to_remind:
		try:
			doc = frappe.get_doc("Maintenance Schedule", d.ms_name)
			doc.send_maintenance_schedule_reminder_notification(d.row_name)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title="Error sending Maintenance Schedule Reminder Notification",
				reference_doctype="Maintenance Scheduler",
				reference_name=d.ms_name,
			)
			frappe.db.commit()

	set_notification_last_scheduled(
		"Maintenance Schedule",
		"",
		"Maintenance Reminder",
		"",
		now_dt=now_dt,
	)


def get_maintenance_schedules_for_reminder_notification(reminder_date=None):
	reminder_date = getdate(reminder_date)

	remind_days_before = cint(frappe.db.get_single_value("Projects Settings", "maintenance_reminder_days_before"))
	if remind_days_before < 1:
		return []

	schedule_date = add_days(reminder_date, remind_days_before)

	schedule_to_remind = frappe.db.sql("""
		SELECT ms.name AS ms_name, msd.name AS row_name, msd.scheduled_date
		FROM `tabMaintenance Schedule Detail` msd
		INNER JOIN `tabMaintenance Schedule` ms ON msd.parent = ms.name
		LEFT JOIN `tabNotification Count` nc ON
			nc.reference_doctype =  'Maintenance Schedule' AND nc.reference_name = ms.name
			AND nc.child_doctype = 'Maintenance Schedule Detail' AND nc.child_name = msd.name
		WHERE ms.status = 'Active'
			AND msd.scheduled_date = %(schedule_date)s
			AND %(reminder_date)s <= msd.scheduled_date
			AND nc.last_scheduled_dt is null
			AND nc.last_sent_dt is null
	""", {
		'schedule_date': schedule_date,
		'reminder_date': reminder_date,
	}, as_dict=1)

	return schedule_to_remind


def get_maintenance_schedules_for_opportunity_creation(for_date=None):
	for_date = getdate(for_date)

	days_in_advance = cint(frappe.get_cached_value("Projects Settings", None, "maintenance_opportunity_reminder_days"))
	if days_in_advance < 0:
		return []

	schedule_date = add_days(for_date, days_in_advance)

	schedules_to_process = frappe.db.sql("""
		select ms.name AS ms_name, msd.name AS row_name, msd.scheduled_date
		from `tabMaintenance Schedule Detail` msd
		inner join `tabMaintenance Schedule` ms on ms.name = msd.parent
		where ms.status = 'Active'
			and msd.scheduled_date = %s
			and not exists(select opp.name from `tabOpportunity` opp
				where opp.maintenance_schedule = ms.name and opp.maintenance_schedule_row = msd.name
			)
	""", schedule_date, as_dict=1)

	return schedules_to_process


def automated_maintenance_opportunity_enabled():
	from frappe.email.doctype.notification.notification import has_notification
	return (
		cint(frappe.db.get_single_value("Projects Settings", "auto_create_opportunity_from_schedule"))
		or has_notification(
			"Maintenance Schedule",
			notification_type="Maintenance Opportunity"
		)
	)


def automated_maintenance_reminder_enabled():
	from frappe.email.doctype.notification.notification import has_notification
	return has_notification(
		"Maintenance Schedule",
		notification_type="Maintenance Reminder"
	)


def get_maintenance_reminder_scheduled_time(reminder_date=None):
	settings = frappe.get_cached_doc("Projects Settings", None)
	reminder_date = getdate(reminder_date)
	reminder_time = settings.maintenance_reminder_time or get_time("00:00:00")
	reminder_dt = combine_datetime(reminder_date, reminder_time)

	return reminder_dt


def get_reminder_date_from_schedule_date(schedule_date):
	settings = frappe.get_cached_doc("Projects Settings", None)
	schedule_date = getdate(schedule_date)

	remind_days_before = cint(settings.maintenance_reminder_days_before)
	if remind_days_before < 0:
		remind_days_before = 0

	reminder_date = add_days(schedule_date, -remind_days_before)
	return reminder_date
