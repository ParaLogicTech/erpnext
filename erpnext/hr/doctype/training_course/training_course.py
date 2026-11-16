# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TrainingCourse(Document):
	def get_topics(self):
		topic_data = []
		for topic in self.topics:
			topic_doc = frappe.get_doc("Training Topic", topic.topic)
			topic_data.append(topic_doc)
		return topic_data
