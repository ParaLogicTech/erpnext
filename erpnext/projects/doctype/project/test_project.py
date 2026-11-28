# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import unittest

import frappe

test_records = frappe.get_test_records("Project")
test_ignore = ["Sales Order"]


class TestProject(unittest.TestCase):
	pass


def make_project(project_details):
	args = frappe._dict(project_details)

	if frappe.db.exists("Project", args.project_name):
		return frappe.get_doc("Project", args.project_name)

	project = frappe.get_doc({
		"doctype": "Project",
		"project_name": args.project_name,
		"status": "Open",
		"expected_start_date": args.start_date,
		"project_date": args.start_date,
	})
	project.insert()

	return project
