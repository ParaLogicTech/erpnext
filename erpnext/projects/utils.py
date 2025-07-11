# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

# For license information, please see license.txt

import frappe
from frappe import _

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def query_task(doctype, txt, searchfield, start, page_len, filters):
	from frappe.desk.reportview import build_match_conditions

	search_string = "%%%s%%" % txt
	order_by_string = "%s%%" % txt
	match_conditions = build_match_conditions("Task")
	match_conditions = ("and" + match_conditions) if match_conditions else ""

	return frappe.db.sql("""select name, subject from `tabTask`
		where (`%s` like %s or `subject` like %s) %s
		order by
			case when `subject` like %s then 0 else 1 end,
			case when `%s` like %s then 0 else 1 end,
			`%s`,
			subject
		limit %s, %s""" %
		(searchfield, "%s", "%s", match_conditions, "%s",
			searchfield, "%s", searchfield, "%s", "%s"),
		(search_string, search_string, order_by_string, order_by_string, start, page_len))

def validate_comma_separated_indices(value, row_idx, max_allowed_idx=None):
	if not value:
		return []

	parts = [x.strip() for x in value.split(',') if x.strip()]
	invalid_format = [x for x in parts if not x.isdigit()]
	if invalid_format:
		frappe.throw(
			_("Row #{0}: Must contain only comma-separated numbers. Invalid value(s): {1}")
			.format(row_idx, ", ".join(invalid_format))
		)

	int_indices = list(map(int, parts))

	if row_idx in int_indices:
		frappe.throw(
			_("Row #{0}: Cannot depend on itself. Please remove index {0} from 'Depends On Task'.").format(row_idx)
		)

	if max_allowed_idx is not None:
		invalid_indices = [i for i in int_indices if i < 1 or i > max_allowed_idx]
		if invalid_indices:
			frappe.throw(
				_("Row #{0}: Invalid task reference(s): {1}. Allowed range: 1 to {2}.")
				.format(row_idx, ", ".join(map(str, invalid_indices)), max_allowed_idx)
			)

	return int_indices


def check_for_circular_dependencies(dependency_map):
	visited = set()
	stack = set()

	def visit(node):
		if node in stack:
			frappe.throw(
				_("Circular dependency detected involving task row #{0}").format(node)
			)
		if node in visited:
			return
		stack.add(node)
		for dep in dependency_map.get(node, []):
			visit(dep)
		stack.remove(node)
		visited.add(node)

	for node in dependency_map:
		visit(node)

