# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, cstr, add_days, get_weekday, format_time, formatdate, get_time, combine_datetime,\
	get_datetime, flt
from erpnext.hr.utils import get_holiday_description, get_employee_leave_policy
from erpnext.hr.report.employee_attendance_sheet.employee_attendance_sheet import get_employee_details,\
	get_attendance_status_abbr, get_attendance_status_color,\
	get_holiday_map, is_date_holiday, get_employee_holiday_list,\
	get_attendance_from_checkins, is_in_employment_date, shift_ended,\
	get_leave_type_map, get_late_deduction_leave_map
from erpnext.hr.doctype.holiday_list.holiday_list import get_default_holiday_list
from erpnext.hr.doctype.shift_assignment.shift_assignment import get_employee_shift


def execute(filters=None):
	filters = frappe._dict(filters)
	validate_filters(filters)

	checkin_map = get_employee_checkin_map(filters)
	attendance_map = get_attendance_map(filters)

	employees = list(set([e for e in checkin_map] + [e for e in attendance_map]))
	employees = sorted(employees)
	employee_map = get_employee_details(filters)

	holiday_map = get_holiday_map(employee_map, filters.default_holiday_list,
		from_date=filters.from_date, to_date=filters.to_date)

	data = []

	checkin_column_count = 1

	current_date = filters.from_date
	while current_date <= filters.to_date:
		day = get_weekday(current_date)
		for employee in employees:
			employee_details = employee_map.get(employee)
			if employee_details:
				row_template = frappe._dict({
					'date': current_date,
					'day': day,
					'employee': employee,
					'employee_name': employee_details.employee_name,
					'department': employee_details.department,
					'designation': employee_details.designation,
					'disable_party_name_formatter': 1,
				})

				is_holiday = is_date_holiday(current_date, holiday_map, employee_details, filters.default_holiday_list)
				row_template['is_holiday'] = is_holiday
				if is_holiday:
					row_template['attendance_status'] = "Holiday"
					row_template['attendance_abbr'] = get_attendance_status_abbr(row_template['attendance_status'])

					employee_holiday_list = get_employee_holiday_list(employee_details, filters.default_holiday_list)
					row_template['remarks'] = get_holiday_description(employee_holiday_list, current_date)

				checkin_shifts = checkin_map.get(employee, {}).get(current_date, {})
				attendance_shifts = attendance_map.get(employee, {}).get(current_date, {})

				shifts = list(set(list(checkin_shifts.keys()) + list(attendance_shifts.keys())))
				if not shifts and is_in_employment_date(current_date, employee_details):
					assigned_shift = get_employee_shift(employee, current_date, True)
					if assigned_shift:
						shifts.append(assigned_shift.shift_type.name)

				if shifts:
					for shift_type in shifts:
						row = row_template.copy()

						checkins = checkin_shifts.get(shift_type, [])
						attendance_details = attendance_shifts.get(shift_type, frappe._dict())

						checkin_column_count = max(checkin_column_count, len(checkins))

						for i, checkin_details in enumerate(checkins):
							checkin_time_fieldname = "checkin_time_{0}".format(i + 1)
							checkin_name_fieldname = "checkin_{0}".format(i + 1)
							row[checkin_name_fieldname] = checkin_details.name

							if getdate(checkin_details.time) != current_date:
								row[checkin_time_fieldname] = "{0} {1}".format(formatdate(checkin_details.time), format_time(checkin_details.time))
							else:
								row[checkin_time_fieldname] = format_time(checkin_details.time)

							if i == 0:
								row['time_in'] = row[checkin_time_fieldname]
							elif i == len(checkins) - 1:
								row['time_out'] = row[checkin_time_fieldname]

						if attendance_details:
							row['attendance'] = attendance_details.name
							row['attendance_status'] = attendance_details.status
							row['attendance_abbr'] = get_attendance_status_abbr(attendance_details.status, attendance_details.late_entry,
								attendance_details.early_exit)
							row['late_entry'] = attendance_details.late_entry
							row['early_exit'] = attendance_details.early_exit
							row['leave_type'] = attendance_details.leave_type
							row['leave_application'] = attendance_details.leave_application
							row['attendance_request'] = attendance_details.attendance_request
							row['remarks'] = attendance_details.remarks or attendance_details.leave_type or attendance_details.attendance_request_reason or row.remarks

							if attendance_details.working_hours:
								row['working_hours'] = attendance_details.working_hours

						row['attendance_marked'] = 1 if attendance_details else 0

						row['shift_type'] = shift_type
						if checkins:
							row['shift_start'] = get_time(checkins[0].shift_start) if checkins[0].shift_start else None
							row['shift_end'] = get_time(checkins[-1].shift_end) if checkins[-1].shift_end else None
						elif shift_type:
							shift_type_doc = frappe.get_cached_doc("Shift Type", shift_type)
							row['shift_start'] = get_time(shift_type_doc.start_time)
							row['shift_end'] = get_time(shift_type_doc.end_time)

						row['shift_start_fmt'] = format_time(row['shift_start'], "hh:mm a") if row.get('shift_start') else None
						row['shift_end_fmt'] = format_time(row['shift_end'], "hh:mm a") if row.get('shift_end') else None

						if not attendance_details and shift_type:
							if checkins:
								attendance_status, working_hours, late_entry, early_exit = get_attendance_from_checkins(checkins,
									shift_type)

								row['attendance_status'] = attendance_status
								row['attendance_abbr'] = get_attendance_status_abbr(attendance_status, late_entry, early_exit)
								row['late_entry'] = late_entry
								row['early_exit'] = early_exit
								if working_hours:
									row['working_hours'] = working_hours
							elif not is_holiday and shift_ended(shift_type, attendance_date=current_date):
								row['attendance_status'] = "Absent"

						row['late_entry_hours'] = get_late_entry_hours(row, checkins)
						row['early_exit_hours'] = get_early_exit_hours(row, checkins)

						row['attendance_color'] = get_attendance_status_color(row.get('attendance_status'))

						data.append(row)
				else:
					data.append(row_template.copy())

		current_date = add_days(current_date, 1)

	totals = None
	if filters.get("employee"):
		totals = calculate_totals(filters.get("employee"), data, filters)

	totals_summary = get_totals_summary(totals)

	columns = get_columns(filters, checkin_column_count, totals)

	return columns, data, None, None, totals_summary


def get_late_entry_hours(row, checkins):
	if not checkins or not row.get("late_entry") or not row.get("shift_start") or not row.get("date"):
		return None

	shift_start_dt = combine_datetime(row.get("date"), row.get("shift_start"))
	first_checkin_dt = get_datetime(checkins[0].time)

	if first_checkin_dt < shift_start_dt:
		return None

	seconds = (first_checkin_dt - shift_start_dt).total_seconds()
	return flt(seconds / 3600, 1)


def get_early_exit_hours(row, checkins):
	if not checkins or not row.get("early_exit") or not row.get("shift_end") or not row.get("date"):
		return None

	shift_end_dt = combine_datetime(row.get("date"), row.get("shift_end"))
	last_checkin_dt = get_datetime(checkins[-1].time)

	if last_checkin_dt > shift_end_dt:
		return None

	seconds = (shift_end_dt - last_checkin_dt).total_seconds()
	return flt(seconds / 3600, 1)


def calculate_totals(employee, data, filters):
	leave_type_map, leave_types = get_leave_type_map()
	late_deduction_leave_map = get_late_deduction_leave_map(filters)

	totals = frappe._dict({
		'total_present': 0,
		'total_absent': 0,
		'total_leave': 0,
		'total_half_day': 0,
		'total_deduction': 0,
		'total_lwp': 0,
		'total_holiday': 0,

		'total_late_entry': 0,
		'total_early_exit': 0,

		"total_working_hours": 0,
		"total_late_entry_hours": 0,
		"total_early_exit_hours": 0,
	})

	for d in data:
		attendance_status = d.attendance_status

		if attendance_status == "Present":
			totals['total_present'] += 1

			if d.late_entry:
				totals['total_late_entry'] += 1
			if d.early_exit:
				totals['total_early_exit'] += 1

		elif attendance_status == "Absent":
			totals['total_absent'] += 1
			totals['total_deduction'] += 1

		elif attendance_status == "Half Day":
			totals['total_half_day'] += 1
			if not d.leave_type:
				totals['total_deduction'] += 0.5

		elif attendance_status == "On Leave":
			leave_details = leave_type_map.get(d.leave_type, frappe._dict())

			if not d.is_holiday or leave_details.include_holidays:
				totals['total_leave'] += 1

		elif attendance_status == "Holiday":
			totals['total_holiday'] += 1

		if attendance_status in ("On Leave", "Half Day") and d.leave_type:
			leave_details = leave_type_map.get(d.leave_type, frappe._dict())
			leave_count = 0.5 if attendance_status == "Half Day" else 1

			if not d.is_holiday or leave_details.include_holidays:
				if leave_details.is_lwp:
					totals['total_deduction'] += leave_count
					totals['total_lwp'] += leave_count

		# total hours
		totals['total_working_hours'] += flt(d.working_hours)
		totals['total_late_entry_hours'] += flt(d.late_entry_hours)
		totals['total_early_exit_hours'] += flt(d.early_exit_hours)

	totals['total_late_deduction'] = 0

	leave_policy = get_employee_leave_policy(employee)
	if leave_policy:
		totals['total_late_deduction'] = leave_policy.get_lwp_from_late_days(totals['total_late_entry'])
		totals['total_deduction'] += totals['total_late_deduction']

	# Late Deduction Leaves
	employee_late_leaves = late_deduction_leave_map.get(employee) or {}
	for leave_type, late_deduction_leave_count in employee_late_leaves.items():
		leave_details = leave_type_map.get(leave_type, frappe._dict())

		totals['total_late_deduction'] -= late_deduction_leave_count
		totals['total_deduction'] -= late_deduction_leave_count

		if leave_details.is_lwp:
			totals['total_late_deduction'] += late_deduction_leave_count
			totals['total_deduction'] += late_deduction_leave_count
			totals['total_lwp'] += late_deduction_leave_count

	totals['total_net_present'] = totals['total_present'] + totals['total_holiday'] + totals['total_half_day'] * 0.5
	totals['total_working_hours'] = flt(totals['total_working_hours'], 1)
	totals['total_late_entry_hours'] = flt(totals['total_late_entry_hours'], 1)
	totals['total_early_exit_hours'] = flt(totals['total_early_exit_hours'], 1)

	return totals


def validate_filters(filters):
	filters.from_date = getdate(filters.from_date)
	filters.to_date = getdate(filters.to_date)

	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date must be before To Date"))

	if not filters.company:
		frappe.throw(_("Please select Company"))

	filters.default_holiday_list = get_default_holiday_list(filters.company)


def get_employee_checkin_map(filters):
	employee_condition = ""
	if filters.employee:
		employee_condition = " and employee = %(employee)s"

	employee_checkins = frappe.db.sql("""
		select *
		from `tabEmployee Checkin`
		where ifnull(employee, '') != '' and (
			date(shift_start) between %(from_date)s and %(to_date)s
			or date(time) between %(from_date)s and %(to_date)s
		)
			{0}
		order by time
	""".format(employee_condition), filters, as_dict=1)

	employee_checkin_map = {}
	for d in employee_checkins:
		date = getdate(d.shift_start) if d.shift_start else getdate(d.time)
		employee_checkin_map.setdefault(d.employee, {}).setdefault(date, {}).setdefault(cstr(d.shift), []).append(d)

	return employee_checkin_map


def get_attendance_map(filters):
	employee_condition = ""
	if filters.employee:
		employee_condition = " and att.employee = %(employee)s"

	attendance = frappe.db.sql("""
		select att.name, att.employee, att.attendance_date, att.shift,
			att.status, att.late_entry, att.early_exit, att.working_hours,
			att.leave_application, att.attendance_request,
			att.remarks, att.leave_type, arq.reason as attendance_request_reason
		from `tabAttendance` att
		left join `tabAttendance Request` arq on arq.name = att.attendance_request
		where att.docstatus = 1 and att.attendance_date between %(from_date)s and %(to_date)s {0}
		order by attendance_date
	""".format(employee_condition), filters, as_dict=1)

	attendance_map = {}
	for d in attendance:
		date = getdate(d.attendance_date)
		attendance_map.setdefault(d.employee, {}).setdefault(date, {}).setdefault(cstr(d.shift), d)

	return attendance_map


def get_columns(filters, checkin_column_count, totals):
	filters.show_employee_name = frappe.db.get_single_value("HR Settings", "emp_created_by") != "Full Name"

	columns = [
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 80, "totals": totals},
		{"fieldname": "day", "label": _("Day"), "fieldtype": "Data", "width": 80},
		{"fieldname": "shift_type", "label": _("Shift Name"), "fieldtype": "Link", "options": "Shift Type", "width": 100},
	]

	if not filters.employee:
		columns.append({"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee",
			"width": 80 if filters.show_employee_name else 150})

		if filters.show_employee_name:
			columns.append({"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 140})

	columns += [
		{"fieldname": "shift_start_fmt", "label": _("Shift Start"), "fieldtype": "Data", "width": 73},
		{"fieldname": "shift_end_fmt", "label": _("Shift End"), "fieldtype": "Data", "width": 73},
	]

	for i in range(checkin_column_count):
		checkin_time_fieldname = "checkin_time_{0}".format(i + 1)
		columns.append({
			"fieldname": checkin_time_fieldname,
			"label": _("Checkin {0}").format(i+1),
			"fieldtype": "Data",
			"width": 85,
			"checkin_idx": i + 1
		})

	columns += [
		{"fieldname": "attendance_status", "label": _("Status"), "fieldtype": "Data", "width": 75},
		{"fieldname": "remarks", "label": _("Remarks"), "fieldtype": "Data", "width": 100},
		{"fieldname": "working_hours", "label": _("W. Hours"), "fieldtype": "Float", "width": 65, "precision": 1},
		{"fieldname": "late_entry_hours", "label": _("Late Hours"), "fieldtype": "Float", "width": 75, "precision": 1},
		{"fieldname": "early_exit_hours", "label": _("Early Exit Hours"), "fieldtype": "Float", "width": 77, "precision": 1},
		{"fieldname": "leave_application", "label": _("Leave Application"), "fieldtype": "Link", "options": "Leave Application", "width": 130},
		{"fieldname": "attendance_request", "label": _("Attendance Request"), "fieldtype": "Link", "options": "Attendance Request", "width": 140},
		{"fieldname": "attendance_marked", "label": _("Confirmed"), "fieldtype": "Check", "width": 75},
	]

	return columns


def get_totals_summary(totals):
	if not totals:
		return None

	return [
		{
			"label": _("Present"),
			"value": totals.total_present,
			"indicator": "green" if totals.total_present > 0 else "grey",
			"datatype": "Float",
			"precision": 1,
		},
		{
			"label": _("Half Days"),
			"value": totals.total_half_day,
			"indicator": "orange" if totals.total_half_day > 0 else "grey",
			"datatype": "Float",
			"precision": 1,
		},
		{
			"label": _("Absent"),
			"value": totals.total_absent,
			"indicator": "red" if totals.total_absent > 0 else "grey",
			"datatype": "Float",
			"precision": 1,
		},
		{
			"label": _("Leaves Taken"),
			"value": totals.total_leave,
			"indicator": "blue" if totals.total_leave > 0 else "grey",
			"datatype": "Float",
			"precision": 1,
		},
		{
			"label": _("Late Entries"),
			"value": totals.total_late_entry,
			"indicator": "orange" if totals.total_late_entry > 0 else "grey",
			"datatype": "Float",
			"precision": 1,
		},
		{
			"label": _("Early Exits"),
			"value": totals.total_early_exit,
			"indicator": "orange" if totals.total_early_exit > 0 else "grey",
			"datatype": "Float",
			"precision": 1,
		},
		{
			"label": _("Late Deduction"),
			"value": totals.total_late_deduction,
			"indicator": "orange" if totals.total_late_deduction > 0 else "grey",
			"datatype": "Float",
			"precision": 1,
		},
		{
			"label": _("Total Deduction"),
			"value": totals.total_deduction,
			"indicator": "red" if totals.total_deduction > 0 else "grey",
			"datatype": "Float",
			"precision": 1,
		},
		{
			"label": _("Total Working Hours"),
			"value": totals.total_working_hours,
			"indicator": "blue" if totals.total_working_hours > 0 else "grey",
			"datatype": "Float",
			"precision": 1,
		},
	]
