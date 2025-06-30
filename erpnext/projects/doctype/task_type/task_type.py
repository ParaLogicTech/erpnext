# -*- coding: utf-8 -*-
# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from erpnext.controllers.checklist_editor import validate_duplicate_checklist_items
from frappe.model.document import Document

class TaskType(Document):
	def validate(self):
		validate_duplicate_checklist_items(self.task_checklist)

