# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate, get_datetime, date_diff, add_days
from erpnext.hr.doctype.shift_assignment.shift_assignment import get_actual_start_end_datetime_of_shift, get_employee_shift
from erpnext.hr.doctype.employee_checkin.employee_checkin import mark_attendance_and_link_log, calculate_working_hours
from erpnext.hr.doctype.attendance.attendance import get_marked_attendance_dates_between, mark_absent
from erpnext.hr.doctype.employee.employee import get_holiday_list_for_employee
from erpnext.hr.doctype.holiday_list.holiday_list import is_holiday, get_holiday_dates_between
from collections import OrderedDict


class ShiftType(Document):
	@frappe.whitelist()
	def enqueue_auto_attendance(self):
		frappe.has_permission("Shift Type", "write", throw=True)

		if not self.process_attendance_after:
			frappe.msgprint(_("Cannot Process Auto Attendance because <b>'Process Attendance After'</b> is not set"))
			return
		if not self.last_sync_of_checkin:
			frappe.msgprint(_("Cannot Process Auto Attendance because <b>'Last Sync of Checkin'</b> is not set"))
			return

		self.queue_action('process_auto_attendance', timeout=600)
		frappe.msgprint(_("Auto Attendance Marking Started"), alert=True)

	def process_auto_attendance(self):
		if not self.process_attendance_after:
			return
		if not self.last_sync_of_checkin:
			return

		update_shift_in_logs(self.process_attendance_after, self.last_sync_of_checkin, publish_progress=True)

		filters = {
			'skip_auto_attendance': '0',
			'attendance': ('is', 'not set'),
			'time': ('>=', self.process_attendance_after),
			'shift_actual_end': ('<', self.last_sync_of_checkin),
			'shift': self.name,
			'employee': ('is', 'set')
		}

		logs = frappe.get_all('Employee Checkin', fields="*", filters=filters, order_by="employee, time")
		grouped_logs = OrderedDict()
		for d in logs:
			key = (d.employee, d.shift_start)
			if key not in grouped_logs:
				grouped_logs[key] = []

			grouped_logs[key].append(d)

		assigned_employees = self.get_assigned_employees(self.process_attendance_after, True)

		total_tasks = len(grouped_logs) + len(assigned_employees)
		completed_tasks = 0

		for (employee, shift_start), single_shift_logs in grouped_logs.items():
			attendance_status, working_hours, late_entry, early_exit = self.get_attendance(single_shift_logs)
			mark_attendance_and_link_log(single_shift_logs, attendance_status, shift_start.date(),
				working_hours, late_entry, early_exit, self.name)

			completed_tasks += 1
			frappe.publish_progress(completed_tasks * 100 / total_tasks,
				title=_("Marking Attendance..."), description=_("Marking Attendance from Checkins"))

		for employee in assigned_employees:
			self.mark_absent_for_dates_with_no_attendance(employee)

			completed_tasks += 1
			frappe.publish_progress(completed_tasks * 100 / total_tasks,
				title=_("Marking Attendance..."), description=_("Marking Absents for missing Attendances"))

	def get_attendance(self, logs, ignore_working_hour_threshold=False):
		"""Return attendance_status, working_hours for a set of logs belonging to a single shift.
		Assumptions:
			1. These logs belong to a single shift, single employee.
			2. Logs are in chronological order
		"""
		status = 'Present'
		late_entry = early_exit = False
		total_working_hours, in_time, out_time = calculate_working_hours(logs, self.determine_check_in_and_check_out, self.working_hours_calculation_based_on)

		employee = logs[0].employee
		shift_date = logs[0].shift_start.date()
		holiday_list = self.get_holiday_list(employee)

		if not is_holiday(holiday_list, shift_date):
			missing_checkin_no_absent = not out_time and self.missing_checkin_no_absent
			missing_checkin_no_half_day = not out_time and self.missing_checkin_no_half_day
			missing_checkin_no_late_entry = not out_time and self.missing_checkin_no_late_entry

			# Late Entry
			if cint(self.enable_entry_grace_period) and in_time and not missing_checkin_no_late_entry\
					and in_time > logs[0].shift_start + timedelta(minutes=cint(self.late_entry_grace_period)):
				late_entry = True

			# Early Exit
			if cint(self.enable_exit_grace_period) and out_time\
					and out_time < logs[0].shift_end - timedelta(minutes=cint(self.early_exit_grace_period)):
				early_exit = True

			# Half Day if Late Minutes
			if cint(self.half_day_if_late_minutes) and in_time and not missing_checkin_no_half_day\
					and in_time > logs[0].shift_start + timedelta(minutes=cint(self.half_day_if_late_minutes)):
				status = 'Half Day'

			# Half Day if Early Exit Minutes
			if cint(self.half_day_if_exit_minutes) and out_time\
					and out_time < logs[0].shift_end - timedelta(minutes=cint(self.half_day_if_exit_minutes)):
				if cint(self.half_day_if_monthly_early_exit_count) > 0:
					if self.is_half_day_on_multiple_early_exit_applicable(employee, logs[0].shift_start):
						status = 'Half Day'
				else:
					status = 'Half Day'

			# Half Day / Absent if working hours less than
			if not ignore_working_hour_threshold:
				if self.working_hours_threshold_for_half_day\
						and total_working_hours < self.working_hours_threshold_for_half_day\
						and not missing_checkin_no_half_day:
					status = 'Half Day'

				if self.working_hours_threshold_for_absent\
						and total_working_hours < self.working_hours_threshold_for_absent\
						and not missing_checkin_no_absent:
					status = 'Absent'

		return status, total_working_hours, late_entry, early_exit

	def is_half_day_on_multiple_early_exit_applicable(self, employee, log_date):
		log_date = getdate(log_date)

		month_start_date = frappe.utils.get_first_day(log_date)
		to_date = add_days(log_date, -1)

		if to_date < month_start_date:
			return False

		early_exit_count = frappe.db.sql("""
			select count(*)
			from `tabAttendance`
			where docstatus = 1 and early_exit = 1 and status = 'Present'
				and employee = %(employee)s and attendance_date between %(from_date)s and %(to_date)s
		""", {"employee": employee, "from_date": month_start_date, "to_date": to_date})
		early_exit_count = cint(early_exit_count[0][0]) if early_exit_count else 0

		return early_exit_count >= cint(self.half_day_if_monthly_early_exit_count)

	def mark_absent_for_dates_with_no_attendance(self, employee):
		"""Marks Absents for the given employee on working days in this shift that have no attendance marked.
		The Absent status is marked starting from 'process_attendance_after' or employee creation date.
		"""
		dates = self.get_dates_for_attendance(employee)

		for date in dates:
			shift_details = get_employee_shift(employee, date, True)
			if shift_details and shift_details.shift_type.name == self.name:
				mark_absent(employee, date, self.name)

	def get_dates_for_attendance(self, employee):
		date_of_joining, relieving_date = frappe.db.get_value("Employee", employee,
			("date_of_joining", "relieving_date"), cache=1)

		if not date_of_joining:
			return []

		start_date = max(getdate(self.process_attendance_after), date_of_joining)
		actual_shift_datetime = get_actual_start_end_datetime_of_shift(employee, get_datetime(self.last_sync_of_checkin), True)
		last_shift_time = actual_shift_datetime[0] if actual_shift_datetime[0] else get_datetime(self.last_sync_of_checkin)
		prev_shift = get_employee_shift(employee, last_shift_time.date()-timedelta(days=1), True, 'reverse')
		if prev_shift:
			end_date = min(prev_shift.start_datetime.date(), relieving_date) if relieving_date else prev_shift.start_datetime.date()
		else:
			return []

		# skip marking absent on holidays and marked attendnace
		date_range = get_date_range(start_date, end_date)
		holiday_list = self.get_holiday_list(employee)
		holiday_dates = get_holiday_dates_between(holiday_list, start_date, end_date)
		marked_attendance_dates = get_marked_attendance_dates_between(employee, start_date, end_date)

		return sorted(set(date_range) - set(holiday_dates) - set(marked_attendance_dates))

	def get_assigned_employees(self, from_date=None, consider_default_shift=False):
		args = {
			"shift_type": self.name,
			"from_date": from_date
		}
		assignment_date_condition = ""
		if from_date:
			assignment_date_condition = " and (end_date >= %(from_date)s or end_date is null)"

		shift_assignment_employees = frappe.db.sql_list("""
			select distinct employee
			from `tabShift Assignment`
			where docstatus = 1 and global_shift = 0 and status = 'Active'
				and shift_type = %(shift_type)s
				{0}
		""".format(assignment_date_condition), args)

		employees = shift_assignment_employees.copy()

		if consider_default_shift:
			default_shift_employees = frappe.db.sql_list("""
				select e.name
				from `tabEmployee` e
				where (e.default_shift = %(shift_type)s or (ifnull(e.default_shift, '') != '' and exists(
					select sa.name
					from `tabShift Assignment` sa
					where sa.company = e.company and sa.docstatus = 1 and sa.global_shift = 1 and sa.status = 'Active'
						and sa.shift_type = %(shift_type)s
						{0}
				)))
			""".format(assignment_date_condition), args)

			employees += default_shift_employees
			employees = list(set(employees))

		return employees

	def get_holiday_list(self, employee):
		return self.holiday_list or get_holiday_list_for_employee(employee, False)


def process_auto_attendance_for_all_shifts():
	shift_list = frappe.get_all('Shift Type', 'name', {'enable_auto_attendance': 1}, as_list=True)
	for shift in shift_list:
		doc = frappe.get_doc('Shift Type', shift[0])
		doc.process_auto_attendance()


@frappe.whitelist()
def update_shift_in_logs(process_attendance_after=None, last_sync_of_checkin=None, publish_progress=True):
	frappe.has_permission("Shift Type", "write", throw=True)

	filters = {
		'skip_auto_attendance': '0',
		'attendance': ('is', 'not set'),
		'shift': ('is', 'set'),
		'employee': ('is', 'set'),
	}

	if not process_attendance_after:
		process_attendance_after = frappe.db.sql("select min(process_attendance_after) from `tabShift Type`")
		process_attendance_after = process_attendance_after[0][0] if process_attendance_after else None

	if process_attendance_after:
		filters['time'] = ('>=', process_attendance_after)
	if last_sync_of_checkin:
		filters['shift_actual_end'] = ('<', last_sync_of_checkin)

	logs = frappe.get_all('Employee Checkin', fields="name", filters=filters)

	total_tasks = len(logs)
	completed_tasks = 0

	for log in logs:
		keys = ("shift", "shift_actual_start", "shift_actual_end", "shift_start", "shift_end")

		log_doc = frappe.get_doc("Employee Checkin", log.name)
		before_values = tuple(log_doc.get(k) for k in keys)

		log_doc.fetch_shift()
		after_values = tuple(log_doc.get(k) for k in keys)

		if after_values != before_values:
			log_doc.flags.ignore_permissions = True
			log_doc.flags.ignore_validate = True
			log_doc.save()

		completed_tasks += 1
		if cint(publish_progress):
			frappe.publish_progress(completed_tasks * 100 / total_tasks,
				title=_("Updating Checkins..."))


def get_date_range(start_date, end_date):
	"""returns list of dates between start and end dates"""
	no_of_days = date_diff(end_date, start_date) + 1
	return [add_days(start_date, i) for i in range(no_of_days)]
