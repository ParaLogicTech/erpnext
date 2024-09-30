# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import json

import frappe
from frappe import _, throw
from frappe.desk.form.assign_to import clear, close_all_assignments
from frappe.model.mapper import get_mapped_doc
from frappe.utils import add_days, cint, cstr, date_diff, get_link_to_form, getdate, today
from frappe.utils.nestedset import NestedSet


class CircularReferenceError(frappe.ValidationError): pass
class EndDateCannotBeGreaterThanProjectEndDateError(frappe.ValidationError): pass


class Task(NestedSet):
	nsm_parent_field = 'parent_task'

	def get_feed(self):
		return '{0}: {1}'.format(_(self.status), self.subject)

	def validate(self):
		self.get_previous_status()
		self.validate_dates()
		self.validate_parent_project_dates()
		self.validate_progress()
		self.validate_status()
		self.validate_assignment()
		self.set_completion_values()
		self.set_is_overdue()
		self.update_depends_on()

	def on_update(self):
		self.update_nsm_model()
		self.check_recursion()
		self.reschedule_dependent_tasks()
		self.update_project()
		self.unassign_todo()
		self.populate_depends_on()

	def on_trash(self):
		if check_if_child_exists(self.name):
			throw(_("Child Task exists for this Task. You can not delete this Task."))

		self.update_nsm_model()

	def after_delete(self):
		self.update_project()

	def get_previous_status(self):
		self._previous_status = self.get_db_value("status")

	def validate_dates(self):
		if self.exp_start_date and self.exp_end_date and getdate(self.exp_start_date) > getdate(self.exp_end_date):
			frappe.throw(_("{0} can not be greater than {1}").format(frappe.bold("Expected Start Date"), \
				frappe.bold("Expected End Date")))

		if self.act_start_date and self.act_end_date and getdate(self.act_start_date) > getdate(self.act_end_date):
			frappe.throw(_("{0} can not be greater than {1}").format(frappe.bold("Actual Start Date"), \
				frappe.bold("Actual End Date")))

	def validate_parent_project_dates(self):
		if not self.project or frappe.flags.in_test:
			return

		expected_end_date = frappe.db.get_value("Project", self.project, "expected_end_date")

		if expected_end_date:
			validate_project_dates(getdate(expected_end_date), self, "exp_start_date", "exp_end_date", "Expected")
			validate_project_dates(getdate(expected_end_date), self, "act_start_date", "act_end_date", "Actual")

	def validate_progress(self):
		if (self.progress or 0) > 100:
			frappe.throw(_("Progress % for a task cannot be more than 100."))

		if self.status == 'Completed':
			self.progress = 100

	def validate_status(self):
		if self.status != self._previous_status and self.status == "Completed":
			for d in self.depends_on:
				if frappe.db.get_value("Task", d.task, "status") not in ("Completed", "Cancelled"):
					frappe.throw(_("Cannot complete task {0} as its dependant {1} is not completed / cancelled.")
						.format(frappe.bold(self.name), frappe.get_desk_link("Task", d.task)))

	def validate_assignment(self):
		if not self.assigned_to:
			self.assigned_to_name = None

		if self.status not in ['Open', 'Cancelled'] and not self.assigned_to:
			frappe.throw(_("'Assigned To' is required for status {0}").format(self.status))

	def set_completion_values(self):
		if self._previous_status in ['Open', 'Working'] and self.status in ["Completed", "Pending Review"]:
			if not self.finish_date:
				self.finish_date = today()

		if self._previous_status == "Pending Review" and self.status == "Completed":
			if not self.review_date:
				self.review_date = today()

	def update_depends_on(self):
		depends_on_tasks = []
		for d in self.depends_on:
			if d.task and d.task not in depends_on_tasks:
				depends_on_tasks.append(d.task)

		self.depends_on_tasks = ", ".join(depends_on_tasks)

	def populate_depends_on(self):
		if self.parent_task:
			parent = frappe.get_doc('Task', self.parent_task)
			if not self.name in [row.task for row in parent.depends_on]:
				parent.append("depends_on", {
					"doctype": "Task Depends On",
					"task": self.name,
					"subject": self.subject
				})
				parent.save()

	def update_nsm_model(self):
		frappe.utils.nestedset.update_nsm(self)

	def unassign_todo(self):
		if self.status == "Completed":
			close_all_assignments(self.doctype, self.name)
		if self.status == "Cancelled":
			clear(self.doctype, self.name)

	def update_total_expense_claim(self):
		self.total_expense_claim = frappe.db.sql("""
			select sum(sanctioned_amount)
			from `tabExpense Claim Detail`
			where project = %s and task = %s and docstatus=1
		""", (self.project, self.name))[0][0]

	def update_time_and_costing(self):
		tl = frappe.db.sql("""
			select min(from_time) as start_date, max(to_time) as end_date,
				sum(billing_amount) as total_billing_amount, sum(costing_amount) as total_costing_amount,
				sum(hours) as time
			from `tabTimesheet Detail`
			where task = %s and docstatus=1
		""", self.name, as_dict=1)[0]

		if self.status == "Open":
			self.status = "Working"

		self.total_costing_amount = tl.total_costing_amount
		self.total_billing_amount = tl.total_billing_amount
		self.actual_time = tl.time
		self.act_start_date = tl.start_date
		self.act_end_date = tl.end_date

	def update_project(self):
		if self.project and not self.flags.from_project:
			doc = frappe.get_doc("Project", self.project)
			doc.set_tasks_status(update=True)
			doc.set_percent_complete(update=True)
			doc.set_status(update=True)
			doc.notify_update()

	def check_recursion(self):
		if self.flags.ignore_recursion_check:
			return

		check_list = [['task', 'parent'], ['parent', 'task']]
		for d in check_list:
			task_list, count = [self.name], 0
			while len(task_list) > count:
				tasks = frappe.db.sql("""
					select {0}
					from `tabTask Depends On`
					where {1} = %s
				""".format(d[0], d[1]), cstr(task_list[count]))
				count = count + 1
				for b in tasks:
					if b[0] == self.name:
						frappe.throw(_("Circular Reference Error"), CircularReferenceError)
					if b[0]:
						task_list.append(b[0])

				if count == 15:
					break

	def reschedule_dependent_tasks(self):
		end_date = self.exp_end_date or self.act_end_date
		if end_date:
			for task_name in frappe.db.sql("""
				select name from `tabTask` as parent
				where parent.project = %(project)s
					and parent.name in (
						select parent from `tabTask Depends On` as child
						where child.task = %(task)s and child.project = %(project)s)
			""", {'project': self.project, 'task':self.name }, as_dict=1):
				task = frappe.get_doc("Task", task_name.name)
				if task.exp_start_date and task.exp_end_date and task.exp_start_date < getdate(end_date) and task.status == "Open":
					task_duration = date_diff(task.exp_end_date, task.exp_start_date)
					task.exp_start_date = add_days(end_date, 1)
					task.exp_end_date = add_days(task.exp_start_date, task_duration)
					task.flags.ignore_recursion_check = True
					task.save()

	def set_is_overdue(self, update=False, update_modified=False):
		self.is_overdue = 0

		if self.status not in ["Completed", "Cancelled"]:
			if self.status == "Pending Review":
				if self.review_date and getdate(self.review_date) < getdate():
					self.is_overdue = 1
			else:
				if self.exp_end_date and getdate(self.exp_end_date) < getdate():
					self.is_overdue = 1

		if update:
			self.db_set('is_overdue', self.is_overdue, update_modified=update_modified)


@frappe.whitelist()
def check_if_child_exists(name):
	child_tasks = frappe.get_all("Task", filters={"parent_task": name})
	child_tasks = [get_link_to_form("Task", task.name) for task in child_tasks]
	return child_tasks


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_project(doctype, txt, searchfield, start, page_len, filters):
	from erpnext.controllers.queries import get_match_cond
	return frappe.db.sql(""" select name from `tabProject`
			where %(key)s like %(txt)s
				%(mcond)s
			order by name
			limit %(start)s, %(page_len)s""" % {
				'key': searchfield,
				'txt': frappe.db.escape('%' + txt + '%'),
				'mcond':get_match_cond(doctype),
				'start': start,
				'page_len': page_len
			})


@frappe.whitelist()
def set_multiple_status(names, status):
	names = json.loads(names)
	for name in names:
		task = frappe.get_doc("Task", name)
		task.status = status
		task.save()


def set_tasks_as_overdue():
	tasks = frappe.get_all("Task", filters={
		"status": ["not in", ["Cancelled", "Completed"]],
		"exp_end_date": ["<", today()],
	})

	for task in tasks:
		doc = frappe.get_doc("Task", task.name)
		doc.set_is_overdue(update=True)


@frappe.whitelist()
def make_timesheet(source_name, target_doc=None, ignore_permissions=False):
	def set_missing_values(source, target):
		target.append("time_logs", {
			"hours": source.actual_time,
			"completed": source.status == "Completed",
			"project": source.project,
			"task": source.name
		})

	doclist = get_mapped_doc("Task", source_name, {
			"Task": {
				"doctype": "Timesheet"
			}
		}, target_doc, postprocess=set_missing_values, ignore_permissions=ignore_permissions)

	return doclist


@frappe.whitelist()
def get_children(doctype, parent, task=None, project=None, status=None, is_root=False):

	filters = [['docstatus', '<', '2']]

	if project:
		filters.append(['project', '=', project])

	if task:
		filters.append(['parent_task', '=', task])
	elif parent and not is_root:
		# via expand child
		filters.append(['parent_task', '=', parent])
	else:
		filters.append(['ifnull(`parent_task`, "")', '=', ''])

	if status:
		if status == "Open":
			filters.append(['status', 'not in', ['Completed', 'Cancelled']])
		elif status == "Completed":
			filters.append(['status', '=', 'Completed'])

	tasks = frappe.get_list(doctype, fields=[
		'name as value',
		'subject as title',
		'is_group as expandable',
		'project',
		'issue'
	], filters=filters, order_by='name')

	# return tasks
	return tasks


@frappe.whitelist()
def add_node():
	from frappe.desk.treeview import make_tree_args
	args = frappe.form_dict
	args.update({
		"name_field": "subject"
	})
	args = make_tree_args(**args)

	if args.parent_task == 'All Tasks' or args.parent_task == args.project:
		args.parent_task = None

	frappe.get_doc(args).insert()


@frappe.whitelist()
def add_multiple_tasks(data, parent):
	data = json.loads(data)
	new_doc = {'doctype': 'Task', 'parent_task': parent if parent!="All Tasks" else ""}
	new_doc['project'] = frappe.db.get_value('Task', {"name": parent}, 'project') or ""

	for d in data:
		if not d.get("subject"): continue
		new_doc['subject'] = d.get("subject")
		new_task = frappe.get_doc(new_doc)
		new_task.insert()


def on_doctype_update():
	frappe.db.add_index("Task", ["lft", "rgt"])


def validate_project_dates(project_end_date, task, task_start, task_end, actual_or_expected_date):
	if task.get(task_start) and date_diff(project_end_date, getdate(task.get(task_start))) < 0:
		frappe.throw(_("Task's {0} Start Date cannot be after Project's End Date.").format(actual_or_expected_date))

	if task.get(task_end) and date_diff(project_end_date, getdate(task.get(task_end))) < 0:
		frappe.throw(_("Task's {0} End Date cannot be after Project's End Date.").format(actual_or_expected_date))
