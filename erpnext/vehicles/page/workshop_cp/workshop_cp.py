import frappe
from frappe import _
from frappe.utils import get_link_to_form, getdate, get_datetime, now_datetime
import json


allowed_sorting_fields = [
	"vehicle_received_date",
	"expected_delivery_date",
	"name",
	"tasks_status",
]


task_count_template = {
	"total_tasks": 0,
	"completed_tasks": 0,
}

task_time_template = {
	'start_dt': None,
	'end_dt': None,
	'time_elapsed': 0
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

	if sort_order.lower() not in ("asc" "desc"):
		frappe.throw(_("Sort Order {0} is invalid").format(sort_order))

	out = {
		"projects": get_projects_data(filters, sort_by, sort_order),
		"tasks": get_tasks_data(filters, sort_by, sort_order),
	}

	return out


def get_projects_data(filters, sort_by, sort_order):
	conditions = get_project_conditions(filters)

	sort_by = f"p.{sort_by}"

	projects_data = frappe.db.sql(f"""
		SELECT
			p.name AS project, p.project_name, p.project_workshop, p.tasks_status,
			p.applies_to_variant_of, p.applies_to_variant_of_name, p.ready_to_close,
			p.applies_to_item, p.applies_to_item_name,
			p.applies_to_vehicle, p.vehicle_chassis_no, p.vehicle_license_plate,
			p.customer, p.customer_name,
			p.expected_delivery_date, p.expected_delivery_time
		FROM `tabProject` p
		LEFT JOIN `tabItem` i ON i.name = p.applies_to_item
		WHERE p.vehicle_status = 'In Workshop'
			{conditions}
		ORDER BY {sort_by} {sort_order}
	""", filters, as_dict=1)

	projects = [d.project for d in projects_data]
	project_task_count = get_project_task_count(projects)
	for d in projects_data:
		count_data = project_task_count.get(d.project, task_count_template.copy())
		if count_data['completed_tasks'] and count_data['total_tasks'] == count_data['completed_tasks'] \
			and d.ready_to_close == 1:
			d.tasks_status = 'Ready'
		d.update(count_data)

	return projects_data


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


def get_project_conditions(filters):
	conditions = []

	if filters.get("project_workshop"):
		conditions.append("p.project_workshop = %(project_workshop)s")

	if filters.get("name"):
		conditions.append("p.name = %(name)s")

	if filters.get("applies_to_item"):
		is_template = frappe.db.get_value("Item", filters.get('applies_to_item'), 'has_variants')
		if is_template:
			conditions.append("i.variant_of=%(applies_to_item)s")
		else:
			conditions.append("i.name=%(applies_to_item)s")

	if filters.get("applies_to_vehicle"):
		conditions.append("p.applies_to_vehicle = %(applies_to_vehicle)s")

	if filters.get("customer"):
		conditions.append("p.customer = %(customer)s")

	if filters.get("status"):
		if filters.get("status") == 'Ready':
			conditions.append("p.ready_to_close = 1")
		else:
			conditions.append("p.tasks_status = %(status)s")

	return "and {0}".format(" and ".join(conditions)) if conditions else ""


def get_tasks_data(filters, sort_by, sort_order):
	conditions = get_project_conditions(filters)
	sort_by = f"p.{sort_by}"

	tasks_data = frappe.db.sql(f"""
		SELECT
			p.applies_to_vehicle, t.project, p.applies_to_variant_of,
			p.applies_to_variant_of_name, p.applies_to_item, p.applies_to_item_name,
			p.vehicle_chassis_no, p.vehicle_license_plate,
			t.subject, t.assigned_to, t.assigned_to_name, t.name, t.status, t.expected_time
		FROM tabTask t
		LEFT JOIN tabProject p ON t.project = p.name
		LEFT JOIN `tabItem` i ON i.name = p.applies_to_item
		WHERE p.vehicle_status = 'In Workshop'
			{conditions}
		ORDER BY {sort_by} {sort_order}
			""", filters, as_dict=1)
	tasks = [d.name for d in tasks_data]
	timesheet_data_map = get_task_time_data(tasks)
	for d in tasks_data:
		d.update(timesheet_data_map.get(d.name, {}))

	return tasks_data


@frappe.whitelist()
def get_task_time_data(tasks):
	if not tasks:
		return []

	timesheet_data = frappe.db.sql("""
		SELECT tsd.task, task.status, tsd.from_time AS start_time, tsd.to_time AS end_time
		FROM `tabTimesheet Detail` tsd
		LEFT JOIN `tabTask` task ON task.name = tsd.task
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


@frappe.whitelist()
def create_template_tasks(project):
	doc = frappe.get_doc("Project", project)

	if not doc.project_templates:
		frappe.throw(_("No Project Templates set in Project {0}".format(get_link_to_form("Project", project))))

	task_created = 0
	for template_task in doc.project_templates:
		filters = {
			"project_template": template_task.project_template,
			"project_template_detail": template_task.name
		}
		if frappe.db.exists("Task", filters):
			frappe.msgprint(_("Task already exist for Project Template: {0}".format(template_task.project_template)))
			continue

		task_doc = frappe.new_doc("Task")
		task_doc.subject = template_task.project_template_name
		task_doc.project = doc.name
		task_doc.update(filters)
		task_doc.save()
		task_created += 1

	frappe.msgprint(_("{0} new tasks created".format(task_created)))


@frappe.whitelist()
def create_custom_tasks(subject, project):
	task_doc = frappe.new_doc("Task")
	task_doc.subject = subject
	task_doc.project = project
	task_doc.save()

	frappe.msgprint(_("The task '{0}' has been successfully created.".format(task_doc.subject)))


@frappe.whitelist()
def assign_technician_task(task, technician, subject):
	task_doc = frappe.get_doc("Task", task)
	task_doc.name = task
	task_doc.assigned_to = technician
	task_doc.subject = subject
	task_doc.save()

	frappe.msgprint(_("Technician for this {0} is assigned".format(task_doc.name)))


@frappe.whitelist()
def reassign_technician_task(task, technician):
	task_doc = frappe.get_doc("Task", task)
	task_doc.assigned_to = technician
	task_doc.assigned_to_name = None
	task_doc.save()


@frappe.whitelist()
def delete_task(task):
	frappe.delete_doc('Task', task)
	frappe.msgprint(_("Task have been deleted".format(task)))


@frappe.whitelist()
def edit_task(task, subject):
	task_doc = frappe.get_doc("Task", task)
	task_doc.name = task
	task_doc.subject = subject
	task_doc.save()


@frappe.whitelist()
def start_task(task):
	task_doc = frappe.get_doc('Task', task)

	if not task_doc.assigned_to:
		frappe.throw(_("Technician is not assigned for {0}").format(frappe.get_desk_link("Task", task_doc)))

	task_doc.status = "Working"
	task_doc.update_project()

	technician_status = frappe.db.get_value("Task", {"assigned_to": task_doc.assigned_to, "status": "Working"})
	if technician_status:
		frappe.throw(_("Technician is already working on {0}").format(frappe.get_desk_link("Task", technician_status)))

	employee = task_doc.assigned_to
	project = task_doc.project
	today = getdate()

	existing_timesheet = frappe.get_all("Timesheet",
		filters={
			"employee": employee,
			"project": project,
			"start_date": today,
			"docstatus": 0,
		},
		fields=["name"]
	)

	if existing_timesheet:
		ts_doc = frappe.get_doc("Timesheet", existing_timesheet[0].name)
	else:
		ts_doc = frappe.new_doc("Timesheet")
		ts_doc.employee = employee
		ts_doc.start_date = today

	ts_doc.append("time_logs", {
		"from_time": get_datetime(),
		"activity_type": "Working",
		"project": project,
		"task": task,
		"to_time": None,
	})

	ts_doc.save()
	task_doc.save()


@frappe.whitelist()
def pause_task(task):
	task_doc = frappe.get_doc('Task', task)

	if task_doc.status != "Working":
		frappe.throw(_("{0} status is not Working.").format(frappe.get_desk_link("Task", task_doc)))

	timesheet_data = frappe.db.sql("""
		SELECT ts.name FROM `tabTimesheet Detail` tsd
		INNER JOIN tabTimesheet ts ON ts.name = tsd.parent
		WHERE ifnull(tsd.to_time, '') = ''
			AND ts.employee = %(assigned_to)s
			AND tsd.task = %(name)s
	""", task_doc.as_dict())

	if timesheet_data:
		ts_doc = frappe.get_doc("Timesheet", timesheet_data[0][0])
		time_log = [d for d in ts_doc.time_logs if not d.to_time][0]
		time_log.to_time = now_datetime()
		ts_doc.save()

	task_doc.status = "On Hold"
	task_doc.save()


@frappe.whitelist()
def complete_task(task):
	task_doc = frappe.get_doc('Task', task)

	if task_doc.status != "Working":
		frappe.throw(_("{0} status is not Working.").format(frappe.get_desk_link("Task", task_doc)))

	timesheet_data = frappe.db.sql("""
		SELECT ts.name FROM `tabTimesheet Detail` tsd
		INNER JOIN tabTimesheet ts ON ts.name = tsd.parent
		WHERE ifnull(tsd.to_time, '') = ''
			AND ts.employee = %(assigned_to)s
			AND tsd.task = %(name)s
	""", task_doc.as_dict())

	if timesheet_data:
		ts_doc = frappe.get_doc("Timesheet", timesheet_data[0][0])
		time_log = [d for d in ts_doc.time_logs if not d.to_time][0]
		time_log.to_time = now_datetime()
		ts_doc.save()

	task_doc.status = "Completed"
	task_doc.save()


@frappe.whitelist()
def resume_task(task):
	task_doc = frappe.get_doc('Task', task)

	if task_doc.status != "On Hold":
		frappe.throw(_("{0} status is not On Hold.").format(frappe.get_desk_link("Task", task_doc)))

	employee = task_doc.assigned_to
	project = task_doc.project
	today = getdate()

	timesheet_data = frappe.get_all("Timesheet",
		filters= {
			"employee": employee,
			"project": project,
			"start_date": today,
			"docstatus": 0
		},
		fields=["name"]
	)

	if timesheet_data:
		ts_doc = frappe.get_doc("Timesheet", timesheet_data[0].name)
	else:
		ts_doc = frappe.new_doc("Timesheet")
		ts_doc.employee = employee
		ts_doc.start_date = today

	ts_doc.append("time_logs", {
		"from_time": get_datetime(),
		"activity_type": "Working",
		"project": project,
		"task": task,
		"to_time": None,
	})

	ts_doc.save()

	task_doc.status = "Working"
	task_doc.save()
