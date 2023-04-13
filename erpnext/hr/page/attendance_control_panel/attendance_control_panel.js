frappe.pages['attendance-control-panel'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Attendance Control Panel',
		single_column: true
	});

	$(wrapper).bind("show", function () {
		$(page.main).append("<div class='attendance-control-panel'></div>");
		frappe.require("attendance_control_panel.bundle.js");
	});
}
