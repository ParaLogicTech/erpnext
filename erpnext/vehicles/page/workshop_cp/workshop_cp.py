import frappe
from frappe import _
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
	}

	return out


def get_projects_data(filters, sort_by, sort_order):
	conditions = get_project_conditions(filters)

	sort_by = f"p.{sort_by}"

	projects_data = frappe.db.sql(f"""
		SELECT
			p.name AS project, p.project_name, p.project_workshop, p.tasks_status,
			p.applies_to_variant_of, p.applies_to_variant_of_name,
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

	return "and {0}".format(" and ".join(conditions)) if conditions else ""