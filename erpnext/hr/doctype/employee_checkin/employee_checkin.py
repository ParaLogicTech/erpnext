# -*- coding: utf-8 -*-
# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import cint, get_datetime
from frappe.model.document import Document
from frappe import _

from erpnext.hr.doctype.shift_assignment.shift_assignment import get_actual_start_end_datetime_of_shift


class EmployeeCheckin(Document):
	def validate(self):
		self.validate_mandatory()
		self.fetch_employee_from_attendance_device_id()
		self.validate_duplicate_log()
		self.fetch_shift()

	def validate_mandatory(self):
		if not self.employee and not self.attendance_device_id:
			frappe.throw(_("Please enter Employee or Attendance Device User ID"))

	def validate_duplicate_log(self):
		employee_condition = "and employee = %(employee)s"
		if not self.employee:
			employee_condition = "and attendance_device_id = %(attendance_device_id)s"

		exclude_condition = "and name != %(name)s" if not self.is_new() else ""

		existing_checkin = frappe.db.sql_list(f"""
			select name
			from `tabEmployee Checkin`
			where time = %(time)s
				{exclude_condition}
				{employee_condition}
			limit 1
		""", {
			"name": self.name,
			"time": self.time,
			"employee": self.employee,
			"attendance_device_id": self.attendance_device_id,
		})
		existing_checkin = existing_checkin[0] if existing_checkin else None

		if existing_checkin:
			frappe.throw(_("This employee already has a log with the same timestamp.{0}").format(
				"<br>" + frappe.get_desk_link("Employee Checkin", existing_checkin)
			))

	def fetch_shift(self):
		if self.attendance:
			return

		has_shift = False
		if self.employee:
			shift_actual_timings = get_actual_start_end_datetime_of_shift(self.employee, get_datetime(self.time), True, True)
			has_shift = shift_actual_timings[0] and shift_actual_timings[1]

		# Log Type validation
		if (has_shift
			and shift_actual_timings[2].shift_type.determine_check_in_and_check_out == "Strictly based on Log Type in Employee Checkin"
			and not self.log_type
			and not self.skip_auto_attendance
		):
			frappe.throw(_('Log Type is required for check-ins falling in the shift: {0}.').format(
				shift_actual_timings[2].shift_type.name)
			)

		if has_shift:
			self.shift = shift_actual_timings[2].shift_type.name
			self.shift_actual_start = shift_actual_timings[0]
			self.shift_actual_end = shift_actual_timings[1]
			self.shift_start = shift_actual_timings[2].start_datetime
			self.shift_end = shift_actual_timings[2].end_datetime
		else:
			self.shift = None
			self.shift_actual_start = None
			self.shift_actual_end = None
			self.shift_start = None
			self.shift_end = None

	def fetch_employee_from_attendance_device_id(self, force=False):
		if not self.attendance_device_id:
			return
		if self.employee and not force:
			return

		employee = frappe.db.get_value("Employee", filters={
			"attendance_device_id": self.attendance_device_id
		}, fieldname=["name as employee", "employee_name", "department", "designation"], as_dict=1)

		if employee:
			self.update(employee)


@frappe.whitelist()
def add_log_based_on_employee_field(employee_field_value, timestamp, device_id=None, log_type=None,
		skip_auto_attendance=0, employee_fieldname="attendance_device_id"):
	"""Finds the relevant Employee using the employee field value and creates a Employee Checkin.

	:param employee_field_value: The value to look for in employee field.
	:param timestamp: The timestamp of the Log. Currently expected in the following format as string: '2019-05-08 10:48:08.000000'
	:param device_id: (optional)Location / Device ID. A short string is expected.
	:param log_type: (optional)Direction of the Punch if available (IN/OUT).
	:param skip_auto_attendance: (optional)Skip auto attendance field will be set for this log(0/1).
	:param employee_fieldname: (Default: attendance_device_id)Name of the field in Employee DocType based on which employee lookup will happen.
	"""

	if not employee_field_value or not timestamp:
		frappe.throw(_("'employee_field_value' and 'timestamp' are required."))

	employee = None
	if employee_fieldname != "attendance_device_id":
		employee = frappe.db.get_value("Employee", {employee_fieldname: employee_field_value},
			["name", "employee_name", employee_fieldname], as_dict=True)

		if not employee:
			frappe.throw(_("No Employee found for the given employee field value. '{}': {}").format(
				employee_fieldname, employee_field_value
			))

	doc = frappe.new_doc("Employee Checkin")
	doc.time = timestamp
	doc.device_id = device_id
	doc.log_type = log_type

	if employee:
		doc.employee = employee.name
		doc.employee_name = employee.employee_name

	if employee_fieldname == "attendance_device_id":
		doc.attendance_device_id = employee_field_value

	if cint(skip_auto_attendance) == 1:
		doc.skip_auto_attendance = 1

	doc.flags.ignore_version = True
	doc.insert()

	frappe.db.commit()
	return doc


def mark_attendance_and_link_log(logs, attendance_status, attendance_date, working_hours=None, late_entry=False, early_exit=False, shift=None):
	"""Creates an attendance and links the attendance to the Employee Checkin.
	Note: If attendance is already present for the given date, the logs are marked as skipped and no exception is thrown.

	:param logs: The List of 'Employee Checkin'.
	:param attendance_status: Attendance status to be marked. One of: (Present, Absent, Half Day, Skip). Note: 'On Leave' is not supported by this function.
	:param attendance_date: Date of the attendance to be created.
	:param working_hours: (optional)Number of working hours for the given date.
	"""
	log_names = [x.name for x in logs]
	employee = logs[0].employee
	if attendance_status == 'Skip':
		frappe.db.sql("""update `tabEmployee Checkin`
			set skip_auto_attendance = %s
			where name in %s""", ('1', log_names))
		return None
	elif attendance_status in ('Present', 'Absent', 'Half Day'):
		if not frappe.db.exists('Attendance', {'employee': employee, 'attendance_date': attendance_date, 'docstatus': 1}):
			doc_dict = {
				'doctype': 'Attendance',
				'employee': employee,
				'attendance_date': attendance_date,
				'status': attendance_status,
				'working_hours': working_hours,
				'company': frappe.db.get_value("Employee", employee, "company", cache=1),
				'shift': shift,
				'late_entry': late_entry,
				'early_exit': early_exit
			}

			attendance = frappe.get_doc(doc_dict)
			attendance.flags.from_auto_attendance = True
			attendance.insert()
			attendance.submit()

			frappe.db.sql("""update `tabEmployee Checkin`
				set attendance = %s
				where name in %s""", (attendance.name, log_names))
			return attendance
		else:
			frappe.db.sql("""update `tabEmployee Checkin`
				set skip_auto_attendance = %s
				where name in %s""", ('1', log_names))
			return None
	else:
		frappe.throw(_('{} is an invalid Attendance Status.').format(attendance_status))


def calculate_working_hours(logs, check_in_out_type, working_hours_calc_type):
	"""Given a set of logs in chronological order calculates the total working hours based on the parameters.
	Zero is returned for all invalid cases.
	
	:param logs: The List of 'Employee Checkin'.
	:param check_in_out_type: One of: 'Alternating entries as IN and OUT during the same shift', 'Strictly based on Log Type in Employee Checkin'
	:param working_hours_calc_type: One of: 'First Check-in and Last Check-out', 'Every Valid Check-in and Check-out'
	"""
	total_hours = 0
	in_time = out_time = None
	if check_in_out_type == 'Alternating entries as IN and OUT during the same shift':
		in_time = logs[0].time
		if len(logs) >= 2:
			out_time = logs[-1].time
		if working_hours_calc_type == 'First Check-in and Last Check-out':
			# assumption in this case: First log always taken as IN, Last log always taken as OUT
			total_hours = time_diff_in_hours(in_time, logs[-1].time)
		elif working_hours_calc_type == 'Every Valid Check-in and Check-out':
			logs = logs[:]
			while len(logs) >= 2:
				total_hours += time_diff_in_hours(logs[0].time, logs[1].time)
				del logs[:2]

	elif check_in_out_type == 'Strictly based on Log Type in Employee Checkin':
		if working_hours_calc_type == 'First Check-in and Last Check-out':
			first_in_log_index = find_index_in_dict(logs, 'log_type', 'IN')
			first_in_log = logs[first_in_log_index] if first_in_log_index or first_in_log_index == 0 else None
			last_out_log_index = find_index_in_dict(reversed(logs), 'log_type', 'OUT')
			last_out_log = logs[len(logs)-1-last_out_log_index] if last_out_log_index or last_out_log_index == 0 else None
			if first_in_log and last_out_log:
				in_time, out_time = first_in_log.time, last_out_log.time
				total_hours = time_diff_in_hours(in_time, out_time)
		elif working_hours_calc_type == 'Every Valid Check-in and Check-out':
			in_log = out_log = None
			for log in logs:
				if in_log and out_log:
					if not in_time:
						in_time = in_log.time
					out_time = out_log.time
					total_hours += time_diff_in_hours(in_log.time, out_log.time)
					in_log = out_log = None
				if not in_log:
					in_log = log if log.log_type == 'IN'  else None
				elif not out_log:
					out_log = log if log.log_type == 'OUT'  else None
			if in_log and out_log:
				out_time = out_log.time
				total_hours += time_diff_in_hours(in_log.time, out_log.time)
	return total_hours, in_time, out_time


def time_diff_in_hours(start, end):
	return round((end-start).total_seconds() / 3600, 1)


def find_index_in_dict(dict_list, key, value):
	return next((index for (index, d) in enumerate(dict_list) if d[key] == value), None)


def update_employee_for_attendance_device_id(attendance_device_id, employee):
	if not attendance_device_id:
		return

	checkins = frappe.get_all("Employee Checkin", filters={
		"attendance_device_id": attendance_device_id,
		"attendance": ("is", "not set"),
	}, pluck="name")

	for name in checkins:
		doc = frappe.get_doc("Employee Checkin", name)
		doc.employee = employee

		if not doc.employee:
			doc.employee_name = None
			doc.department = None
			doc.designation = None

		doc.save(ignore_permissions=True)

	return len(checkins)
