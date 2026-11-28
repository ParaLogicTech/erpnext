# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import unittest

import frappe

from erpnext.hr.doctype.leave_type.test_leave_type import create_leave_type


class TestLeavePolicy(unittest.TestCase):
	def test_max_leave_allowed(self):
		# a leave type of its own, as other tests allocate more than 2 leaves of theirs
		leave_type = create_leave_type(leave_type_name="_Test Leave Type Max Allowed")
		leave_type.max_leaves_allowed = 2
		leave_type.save()

		leave_policy = create_leave_policy(leave_type=leave_type.name, annual_allocation=leave_type.max_leaves_allowed + 1)

		self.assertRaises(frappe.ValidationError, leave_policy.insert)


def create_leave_policy(**args):
	""" Returns an object of leave policy """
	args = frappe._dict(args)
	return frappe.get_doc({
		"doctype": "Leave Policy",
		"leave_policy_details": [{
			"leave_type": args.leave_type or "_Test Leave Type",
			"annual_allocation": args.annual_allocation or 10,
		}],
	})
