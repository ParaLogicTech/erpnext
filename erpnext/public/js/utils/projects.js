frappe.provide("erpnext.projects");

erpnext.projects.create_task = function(project, subject, standard_time, project_template) {
	let task_doc = frappe.new_doc("Task");
	task_doc.project = project;
	task_doc.subject = subject;
	task_doc.expected_time = flt(standard_time);
	task_doc.project_template = project_template;

	task_doc.save(null, () => {
		frappe.msgprint(_("{0} created").format(frappe.get_link(task_doc)), { indicator: "green" });
	});
};
