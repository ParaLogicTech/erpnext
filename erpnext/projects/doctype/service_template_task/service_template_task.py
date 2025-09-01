# -*- coding: utf-8 -*-
# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _

class ServiceTemplateTask(Document):
	def validate_depends_on_task(self):
		if not self.depends_on_task:
			return

		parts = [x.strip() for x in self.depends_on_task.split(',') if x.strip()]
		for part in parts:
			if not part.isdigit():
				frappe.throw(
					_("Row #{0}: 'Depends On Task' must only contain comma-separated numbers. Found invalid value: {1}").format(
						self.idx, part))

		invalid_indices = [int(x) for x in parts if int(x) >= self.idx]
		if invalid_indices:
			frappe.throw(_("Row #{0}: 'Depends On Task' cannot refer to current or future rows: {1}").format(
				self.idx, ", ".join(str(x) for x in invalid_indices)
			))
