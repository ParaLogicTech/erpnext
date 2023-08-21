import frappe
from frappe import _
import json


allowed_sorting_fields = [
	"vehicle_received_date",
	"expected_delivery_date",
	"name",
	# "task_status",
]


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

	table_data = frappe.db.sql(f"""
		SELECT
			p.name AS project, p.project_name, p.project_workshop,
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

	return table_data


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