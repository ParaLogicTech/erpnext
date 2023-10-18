import frappe
from frappe import _
from frappe.utils import get_url_to_form, get_datetime, now_datetime, flt, cint, getdate
import json


allowed_sorting_fields = [
	"project",
	"vehicle_received_date",
	"expected_delivery_date",
	"tasks_status",
]

task_count_template = {
	"total_tasks": 0,
	"completed_tasks": 0,
}

task_time_template = {
	"start_dt": None,
	"end_dt": None,
	"time_elapsed": 0
}

task_status_color_map = {
	"Open": "orange",
	"Working": "purple",
	"On Hold": "red",
	"Completed": "green",
	"Cancelled": "light-gray"
}

project_status_color_map = {
	"No Tasks": "gray",
	"Not Started": "orange",
	"In Progress": "purple",
	"On Hold": "red",
	"Completed": "light-blue",
	"Ready": "green",
	"Delivered": "green",
}


@frappe.whitelist()
def get_workshop_cp_data(filters, sort_by=None, sort_order=None):
	if isinstance(filters, str):
		filters = json.loads(filters)

	if not sort_by:
		sort_by = "vehicle_received_date"
	if not sort_order:
		sort_order = "asc"

	if sort_by not in allowed_sorting_fields:
		frappe.throw(_("Sort By {0} is not allowed").format(sort_by))

	if sort_order.lower() not in ("asc", "desc"):
		frappe.throw(_("Sort Order {0} is invalid").format(sort_order))

	out = frappe._dict({
		"projects": get_projects_data(filters),
		"tasks": get_tasks_data(filters),
	})

	project_names = [d.project for d in out.projects]
	project_task_count = get_project_task_count(project_names)

	task_names = [d.task for d in out.tasks]
	timesheet_data_map = get_task_time_data(task_names)

	postprocess_projects_data(out.projects, project_task_count)
	postprocess_projects_data(out.tasks, project_task_count)
	postprocess_tasks_data(out.tasks, timesheet_data_map)

	out.projects = sorted(out.projects, key=lambda d: d[sort_by], reverse=sort_order == "desc")
	out.tasks = sorted(out.tasks, key=lambda d: (d[sort_by], d.project, d.creation), reverse=sort_order == "desc")

	return out


def postprocess_projects_data(data, project_task_count):
	for d in data:
		count_data = project_task_count.get(d.project, task_count_template.copy())
		d.update(count_data)

		if d.vehicle_delivered_date:
			d.tasks_status = "Delivered"
		elif d.ready_to_close and count_data['total_tasks'] == count_data['completed_tasks']:
			d.tasks_status = "Ready"

		d.project_status_color = project_status_color_map.get(d.tasks_status, 'black')


def postprocess_tasks_data(data, timesheet_data_map):
	for d in data:
		d.task_status_color = task_status_color_map.get(d.status, 'black')
		d.update(timesheet_data_map.get(d.task, {}))


def get_projects_data(filters):
	conditions = get_project_conditions(filters)

	projects_data = frappe.db.sql(f"""
		SELECT
			p.name as project, p.project_name, p.project_workshop, p.tasks_status,
			p.applies_to_variant_of, p.applies_to_variant_of_name, p.ready_to_close,
			p.applies_to_item, p.applies_to_item_name,
			p.applies_to_vehicle, p.vehicle_chassis_no, p.vehicle_license_plate,
			p.customer, p.customer_name,
			p.expected_delivery_date, p.expected_delivery_time, p.vehicle_received_date, p.vehicle_delivered_date
		FROM `tabProject` p
		LEFT JOIN `tabItem` i ON i.name = p.applies_to_item
		WHERE {conditions}
	""", filters, as_dict=1)

	return projects_data


def get_tasks_data(filters):
	conditions = get_project_conditions(filters)

	tasks_data = frappe.db.sql(f"""
		SELECT
			t.name as task, t.subject, t.assigned_to, t.assigned_to_name, t.status, t.expected_time,
			p.applies_to_vehicle, t.project, p.applies_to_variant_of,
			p.applies_to_variant_of_name, p.applies_to_item, p.applies_to_item_name,
			p.vehicle_chassis_no, p.vehicle_license_plate, p.ready_to_close,
			p.tasks_status, t.creation, p.vehicle_received_date, p.expected_delivery_date, p.vehicle_delivered_date
		FROM tabTask t
		INNER JOIN tabProject p ON t.project = p.name
		LEFT JOIN `tabItem` i ON i.name = p.applies_to_item
		WHERE {conditions}
	""", filters, as_dict=1)

	return tasks_data


def get_project_task_count(projects):
	tasks_data = []
	if projects:
		tasks_data = frappe.db.sql("""
			SELECT t.name as task, t.project, t.status
			FROM `tabTask` t
			WHERE t.project in %(projects)s and t.status != 'Cancelled'
		""", {"projects": projects}, as_dict=1)

	project_task_count = {}

	for d in tasks_data:
		project_data = project_task_count.setdefault(d.project, task_count_template.copy())
		project_data["total_tasks"] += 1

		if d.status == "Completed":
			project_data["completed_tasks"] += 1

	return project_task_count


def get_task_time_data(tasks):
	if not tasks:
		return []

	timesheet_data = frappe.db.sql("""
		SELECT tsd.task, task.status, tsd.from_time AS start_time, tsd.to_time AS end_time
		FROM `tabTimesheet Detail` tsd
		INNER JOIN `tabTask` task ON task.name = tsd.task
		WHERE tsd.task IN %(tasks)s
	""", {"tasks": tasks}, as_dict=1)

	timesheet_data_map = frappe._dict()
	for d in timesheet_data:
		timesheet_data_map.setdefault(d.task, task_time_template.copy())
		end_time = get_datetime(d.end_time)
		timesheet_data_map[d.task]['time_elapsed'] += (end_time - get_datetime(d.start_time)).total_seconds() / 3600
		timesheet_data_map[d.task]['start_dt'] = min(get_datetime(timesheet_data_map[d.task]['start_dt']), get_datetime(d.start_time))

		if d.status == "Completed" and d.end_time:
			if not timesheet_data_map[d.task]['end_dt']:
				timesheet_data_map[d.task]['end_dt'] = get_datetime(d.end_time)
			else:
				timesheet_data_map[d.task]['end_dt'] = max(get_datetime(timesheet_data_map[d.task]['end_dt']), get_datetime(d.end_time))

	return timesheet_data_map


def get_project_conditions(filters):
	conditions = []

	today = getdate()

	if filters.get("project"):
		conditions.append("p.name = %(project)s")
	else:
		conditions.append("(p.vehicle_status = 'In Workshop' or p.vehicle_delivered_date = {0})".format(
			frappe.db.escape(today)
		))

	if filters.get("project_workshop"):
		conditions.append("p.project_workshop = %(project_workshop)s")

	if filters.get("applies_to_item"):
		is_template = frappe.db.get_value("Item", filters.get('applies_to_item'), 'has_variants')
		if is_template:
			conditions.append("i.variant_of = %(applies_to_item)s")
		else:
			conditions.append("i.name = %(applies_to_item)s")

	if filters.get("applies_to_vehicle"):
		conditions.append("p.applies_to_vehicle = %(applies_to_vehicle)s")

	if filters.get("customer"):
		conditions.append("p.customer = %(customer)s")

	if filters.get("status"):
		if filters.get("status") == 'Ready':
			conditions.append("p.ready_to_close = 1")
		else:
			conditions.append("p.tasks_status = %(status)s")
			conditions.append("p.ready_to_close = 0")

	return " and ".join(conditions)


@frappe.whitelist()
def create_template_tasks(project):
	doc = frappe.get_doc("Project", project)

	if not doc.project_templates:
		frappe.throw(_("No Project Template set in {0}".format(get_link_from_name("Project", project))))

	tasks_created = []
	for d in doc.project_templates:
		filters = {
			"project_template": d.project_template,
			"project_template_detail": d.name
		}
		if frappe.db.exists("Task", filters):
			continue

		task_doc = frappe.new_doc("Task")
		task_doc.subject = d.project_template_name
		task_doc.project = doc.name
		task_doc.expected_time = get_standard_working_hours(d.project_template)
		task_doc.project_template = d.project_template
		task_doc.project_template_detail = d.name

		task_doc.save()
		tasks_created.append(task_doc)

	if tasks_created:
		frappe.msgprint(_("{0} template tasks created against {1}<br><br><ul>{2}</ul>").format(
			len(tasks_created),
			get_link_from_name("Project", doc.name),
			"".join([f"<li>{get_link(d)}</li>" for d in tasks_created])
		), indicator="green")
	else:
		frappe.msgprint(_("Template tasks against {0} already exist").format(
			get_link_from_name("Project", doc.name)
		))


@frappe.whitelist()
def create_task(project, subject=None, standard_time=None, project_template=None):
	task_doc = frappe.new_doc("Task")
	task_doc.project = project

	if project_template:
		project_template_name = frappe.get_cached_value("Project Template", project_template, "project_template_name")

		task_doc.subject = subject or project_template_name
		task_doc.expected_time = flt(standard_time) or get_standard_working_hours(project_template)
		task_doc.project_template = project_template
	else:
		if not subject:
			frappe.throw(_("Subject is mandatory"))

		task_doc.subject = subject
		task_doc.expected_time = flt(standard_time)

	task_doc.save()

	frappe.msgprint(_("{0} created").format(
		get_link(task_doc)
	), indicator="green")


@frappe.whitelist()
def get_standard_working_hours(project_template):
	standard_working_hours = frappe.db.sql("""
		SELECT item.item_code, item.standard_working_hours
		FROM `tabProject Template Item` pti
		INNER JOIN tabItem item  ON pti.applicable_item_code = item.item_code
		WHERE pti.parent = %(project_template)s
	""", {"project_template": project_template}, as_dict=1)

	return sum(flt(d.standard_working_hours) for d in standard_working_hours)


@frappe.whitelist()
def assign_technician_task(task, technician):
	task_doc = frappe.get_doc("Task", task)
	validate_project_set_in_task(task_doc)

	if not technician:
		frappe.throw(_("Technician not provided"))

	if task_doc.assigned_to:
		frappe.throw(_("{0} is already assigned to Technician {1}").format(
			get_link(task_doc),
			frappe.bold(task_doc.assigned_to_name or task_doc.assigned_to)
		))

	task_doc.assigned_to = technician
	task_doc.save()

	frappe.msgprint(_("{0} assigned to Technician {1}").format(
		get_link(task_doc),
		frappe.bold(task_doc.assigned_to_name or task_doc.assigned_to)
	), alert=True, indicator="green")


@frappe.whitelist()
def reassign_technician_task(task, technician):
	task_doc = frappe.get_doc("Task", task)
	validate_project_set_in_task(task_doc)

	if not task_doc.assigned_to:
		frappe.throw(_("Cannot reassign {0} because it is not assigned to anyone").format(
			get_link(task_doc)
		))

	if task_doc.status in ("Completed", "Cancelled"):
		frappe.throw(_("Cannot reassign {0} because its status is {1}").format(
			get_link(task_doc),
			frappe.bold(task_doc.status)
		))

	if task_doc.assigned_to == technician:
		frappe.throw(_("{0} is already assigned to {1}").format(
			frappe.bold(task_doc.assigned_to_name or task_doc.assigned_to)
		))

	if task_doc.assigned_to:
		stop_timesheet_log(task_doc.name, task_doc.assigned_to, completed=0)

	task_doc.assigned_to = technician

	if task_doc.status != "Open":
		task_doc.status = "On Hold"

	task_doc.save()

	if not technician:
		frappe.msgprint(_("{0} has been unassigned").format(
			get_link(task_doc)
		), alert=True, indicator="green")
	else:
		frappe.msgprint(_("{0} reassigned to Technician {1}").format(
			get_link(task_doc),
			frappe.bold(task_doc.assigned_to_name or task_doc.assigned_to)
		), alert=True, indicator="green")


@frappe.whitelist()
def edit_task(task, subject, standard_time=None):
	task_doc = frappe.get_doc("Task", task)
	validate_project_set_in_task(task_doc)

	if not subject:
		frappe.throw(_("Subject is mandatory"))

	if task_doc.status == "Completed":
		frappe.throw(_("Cannot edit {0} because its status is {1}").format(
			get_link(task_doc),
			frappe.bold(task_doc.status)
		))

	validate_project_not_ready_to_close(task_doc, _("edit"))

	task_doc.subject = subject
	if flt(standard_time):
		task_doc.expected_time = flt(standard_time)

	task_doc.save()

	frappe.msgprint(_("{0} edited").format(
		get_link(task_doc)
	), alert=True, indicator="green")


@frappe.whitelist()
def cancel_task(task):
	task_doc = frappe.get_doc("Task", task)
	validate_project_set_in_task(task_doc)

	if task_doc.status != "Open":
		frappe.throw(_("Cannot cancel {0} because its status is {1}").format(
			get_link(task_doc),
			frappe.bold(task_doc.status)
		))

	validate_project_not_ready_to_close(task_doc, _("cancel"))

	task_doc.status = "Cancelled"
	task_doc.save()

	frappe.msgprint(_("{0} cancelled").format(
		get_link(task_doc)
	), indicator="green")


@frappe.whitelist()
def start_task(task):
	task_doc = frappe.get_doc("Task", task)
	validate_project_set_in_task(task_doc)

	if not task_doc.assigned_to:
		frappe.throw(_("Technician is not assigned for {0}").format(get_link(task_doc)))

	if task_doc.status != "Open":
		frappe.throw(_("Cannot start {0} because its status is {1}").format(
			get_link(task_doc),
			frappe.bold(task_doc.status)
		))

	check_technician_available(task_doc.assigned_to, throw=True)

	add_timesheet_log(task_doc.name, task_doc.project, task_doc.assigned_to)

	task_doc.status = "Working"
	task_doc.save()

	frappe.msgprint(_("{0} started").format(
		get_link(task_doc)
	), alert=True, indicator="green")


@frappe.whitelist()
def resume_task(task):
	task_doc = frappe.get_doc("Task", task)
	validate_project_set_in_task(task_doc)

	if task_doc.status not in ["On Hold", "Completed"]:
		frappe.throw(_("Cannot resume {0} because its status is {1}").format(
			get_link(task_doc),
			frappe.bold(task_doc.status)
		))

	validate_project_not_ready_to_close(task_doc, _("resume"))

	check_technician_available(task_doc.assigned_to, throw=True)

	add_timesheet_log(task_doc.name, task_doc.project, task_doc.assigned_to)

	task_doc.status = "Working"
	task_doc.save()

	frappe.msgprint(_("{0} resumed").format(
		get_link(task_doc)
	), alert=True, indicator="green")


@frappe.whitelist()
def pause_task(task):
	task_doc = frappe.get_doc("Task", task)
	validate_project_set_in_task(task_doc)

	if task_doc.status != "Working":
		frappe.throw(_("Cannot pause {0} because its status is {1}").format(
			get_link(task_doc),
			frappe.bold(task_doc.status)
		))

	stop_timesheet_log(task_doc.name, task_doc.assigned_to, completed=0)

	task_doc.status = "On Hold"
	task_doc.save()

	frappe.msgprint(_("{0} paused").format(
		get_link(task_doc)
	), alert=True, indicator="green")


@frappe.whitelist()
def complete_task(task):
	task_doc = frappe.get_doc("Task", task)

	if task_doc.status not in ("Working", "Pending Review", "On Hold"):
		frappe.throw(_("Cannot complete {0} because its status is {1}").format(
			get_link(task_doc),
			frappe.bold(task_doc.status)
		))

	stop_timesheet_log(task_doc.name, task_doc.assigned_to, completed=1)

	task_doc.status = "Completed"
	task_doc.save()

	frappe.msgprint(_("{0} completed").format(
		get_link(task_doc)
	), alert=True, indicator="green")


def check_technician_available(employee, throw=False):
	working_task = frappe.db.get_value("Task", {"assigned_to": employee, "status": "Working"})
	if working_task:
		if throw:
			frappe.throw(_("Technician {0} is already working on {1}").format(
				frappe.bold(frappe.get_cached_value("Employee", employee, "employee_name")),
				get_link_from_name("Task", working_task)
			))

		return False

	return True


def add_timesheet_log(task, project, assigned_to):
	existing_timesheet = frappe.get_all("Timesheet",
		filters={
			"employee": assigned_to,
			"project": project,
			"docstatus": 0
		},
		fields=["name"]
	)

	if existing_timesheet:
		ts_doc = frappe.get_doc("Timesheet", existing_timesheet[0].name)
	else:
		ts_doc = frappe.new_doc("Timesheet")
		ts_doc.employee = assigned_to

	ts_doc.append("time_logs", {
		"from_time": get_datetime(),
		"project": project,
		"task": task,
		"to_time": None,
	})

	ts_doc.save()


def stop_timesheet_log(task, assigned_to, completed):
	running_timesheet = frappe.db.sql("""
		SELECT ts.name
		FROM `tabTimesheet Detail` tsd
		INNER JOIN tabTimesheet ts ON ts.name = tsd.parent
		WHERE ifnull(tsd.to_time, '') = ''
			AND ts.employee = %(assigned_to)s
			AND tsd.task = %(task)s
	""", {
		"task": task,
		"assigned_to": assigned_to,
	})

	running_timesheet = running_timesheet[0][0] if running_timesheet else None
	if running_timesheet:
		ts_doc = frappe.get_doc("Timesheet", running_timesheet)
		time_log = [d for d in ts_doc.time_logs if not d.to_time][0]
		time_log.to_time = now_datetime()
		time_log.completed = cint(completed)
		ts_doc.save()


def validate_project_not_ready_to_close(task_doc, action_label):
	validate_project_set_in_task(task_doc)
	ready_to_close = frappe.db.get_value("Project", task_doc.project, "ready_to_close")

	if ready_to_close:
		frappe.throw(_("Cannot {0} {1} because {2} is Ready to Close").format(
			action_label,
			get_link(task_doc),
			get_link_from_name("Project", task_doc.project)
		))


def validate_project_set_in_task(task_doc):
	if not task_doc.project:
		frappe.throw(_("{0} is not against any {1}").format(
			get_link(task_doc),
			_("Project")
		))


def get_link(doc):
	return get_link_from_name(doc.doctype, doc.name, doc)


def get_link_from_name(doctype, name, doc=None):
	if doctype == "Task":
		subject = doc.subject if doc else frappe.db.get_value("Task", name, "subject")
		return f"<a href='{get_url_to_form(doctype, name)}'>{name} ({subject})</a>"
	else:
		return frappe.get_desk_link(doctype, name)
