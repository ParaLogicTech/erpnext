# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import flt, cint, getdate, formatdate, comma_and, time_diff_in_seconds, to_timedelta
from frappe.model.document import Document


class WorkstationHolidayError(frappe.ValidationError): pass
class NotInWorkingHoursError(frappe.ValidationError): pass
class OverlapError(frappe.ValidationError): pass


class Workstation(Document):
	def validate(self):
		self.validate_allowed_operations()
		self.calculate_hour_rate()

	def on_update(self):
		self.validate_overlap_for_operation_timings()
		self.update_bom_operation()

	def validate_allowed_operations(self):
		operations = set()
		for d in self.allowed_operations:
			if d.operation in operations or operations.add(d.operation):
				frappe.throw(_("Row #{0}: Operation {1} is entrered twice").format(d.idx, frappe.bold(d.operation)))

	def calculate_hour_rate(self):
		self.hour_rate = (flt(self.hour_rate_labour) + flt(self.hour_rate_electricity) +
			flt(self.hour_rate_consumable) + flt(self.hour_rate_rent))

	def validate_overlap_for_operation_timings(self):
		"""Check if there is no overlap in setting Workstation Operating Hours"""
		for d in self.get("working_hours"):
			existing = frappe.db.sql_list("""select idx from `tabWorkstation Working Hour`
				where parent = %s and name != %s
					and (
						(start_time between %s and %s) or
						(end_time between %s and %s) or
						(%s between start_time and end_time))
				""", (self.name, d.name, d.start_time, d.end_time, d.start_time, d.end_time, d.start_time))

			if existing:
				frappe.throw(_("Row #{0}: Timings conflicts with row {1}").format(d.idx, comma_and(existing)), OverlapError)

	def update_bom_operation(self):
		bom_list = frappe.db.sql("""select DISTINCT parent from `tabBOM Operation`
			where workstation = %s""", self.name)
		for bom_no in bom_list:
			frappe.db.sql("""update `tabBOM Operation` set hour_rate = %s
				where parent = %s and workstation = %s""",
				(self.hour_rate, bom_no[0], self.name))


@frappe.whitelist()
def get_default_holiday_list():
	from erpnext.hr.doctype.holiday_list.holiday_list import get_default_holiday_list
	return get_default_holiday_list(frappe.defaults.get_user_default("Company"))


def check_if_within_operating_hours(workstation, operation, from_datetime, to_datetime):
	if from_datetime and to_datetime:
		if not cint(frappe.db.get_value("Manufacturing Settings", "None", "allow_production_on_holidays")):
			check_workstation_for_holiday(workstation, from_datetime, to_datetime)

		if not cint(frappe.db.get_value("Manufacturing Settings", None, "allow_overtime")):
			is_within_operating_hours(workstation, operation, from_datetime, to_datetime)


def is_within_operating_hours(workstation, operation, from_datetime, to_datetime):
	operation_length = time_diff_in_seconds(to_datetime, from_datetime)
	workstation = frappe.get_doc("Workstation", workstation)
	
	if not workstation.working_hours:
		return

	for working_hour in workstation.working_hours:
		if working_hour.start_time and working_hour.end_time:
			slot_length = (to_timedelta(working_hour.end_time or "") - to_timedelta(working_hour.start_time or "")).total_seconds()
			if slot_length >= operation_length:
				return

	frappe.throw(_("Operation {0} longer than any available working hours in workstation {1}, break down the operation into multiple operations").format(operation, workstation.name), NotInWorkingHoursError)


def check_workstation_for_holiday(workstation, from_datetime, to_datetime):
	holiday_list = frappe.db.get_value("Workstation", workstation, "holiday_list")
	if holiday_list and from_datetime and to_datetime:
		applicable_holidays = []
		for d in frappe.db.sql("""select holiday_date from `tabHoliday` where parent = %s
			and holiday_date between %s and %s """,
			(holiday_list, getdate(from_datetime), getdate(to_datetime))):
				applicable_holidays.append(formatdate(d[0]))

		if applicable_holidays:
			frappe.throw(_("Workstation is closed on the following dates as per Holiday List: {0}")
				.format(holiday_list) + "\n" + "\n".join(applicable_holidays), WorkstationHolidayError)
