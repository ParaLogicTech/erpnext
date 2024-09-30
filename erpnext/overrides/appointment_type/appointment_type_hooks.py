# import frappe
from frappe.utils import getdate
from crm.crm.doctype.appointment_type.appointment_type import AppointmentType
from erpnext.hr.doctype.holiday_list.holiday_list import get_default_holiday_list, is_holiday


class AppointmentTypeERP(AppointmentType):
	def is_holiday(self, date):
		if super().is_holiday(date):
			return True

		date = getdate(date)
		holiday_list = self.get_holiday_list()
		return is_holiday(holiday_list, date)

	def get_holiday_list(self):
		if self.get("holiday_list"):
			return self.holiday_list
		elif self.get("company"):
			return get_default_holiday_list(self.company)
		else:
			return None
