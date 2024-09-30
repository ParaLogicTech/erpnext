# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class Topic(Document):
	def get_contents(self):
		try:
			topic_content_list = self.topic_content
			content_data = [frappe.get_doc(topic_content.content_type, topic_content.content) for topic_content in topic_content_list]
		except Exception as e:
			frappe.log_error(message=frappe.get_traceback())
			return None
		return content_data