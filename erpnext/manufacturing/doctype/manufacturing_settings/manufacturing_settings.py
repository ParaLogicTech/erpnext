# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint
from dateutil.relativedelta import relativedelta


class ManufacturingSettings(Document):
	def validate(self):
		self.update_global_defaults()

	def update_global_defaults(self):
		for key in ["overproduction_percentage_for_work_order", "process_loss_remaining_by_default", "disable_capacity_planning"]:
			frappe.db.set_default(key, self.get(key, ""))


def get_mins_between_operations():
	return relativedelta(minutes=cint(frappe.db.get_single_value("Manufacturing Settings",
		"mins_between_operations")) or 10)
