import frappe


def execute():
	tasks = frappe.db.sql("""
		select t.name, t.status as task_status, t.actual_time, p.status as project_status, t.project
		from `tabTask` t
		inner join `tabProject` p on t.project = p.name
		where
			(p.status in ('Completed', 'Closed', 'Cancelled') or p.ready_to_close = 1)
			and t.status not in ('Completed', 'Cancelled')
	""", as_dict=1)

	for d in tasks:
		status = "Completed" if d.actual_time else "Cancelled"
		frappe.db.set_value("Task", d.name, "status", status)

		print(f"{status} Task {d.name} against {d.project}, Task Status {d.task_status}, Project Status {d.project_status}")
