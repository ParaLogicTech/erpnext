// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt


frappe.query_reports["Employee Checkin Sheet"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 1
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
			on_change: () => {
				let employee = frappe.query_report.get_filter_value('employee');
				if (employee) {
					frappe.db.get_value('Employee', employee, ["employee_name", "designation", "department"], function(value) {
						frappe.query_report.set_filter_value(value);
					});
				} else {
					frappe.query_report.set_filter_value('employee_name', "");
					frappe.query_report.set_filter_value('designation', "");
					frappe.query_report.set_filter_value('department', "");
				}
			},
		},
		{
			fieldname: "employee_name",
			label: __("Employee Name"),
			fieldtype: "Data",
			read_only: 1,
			on_change: () => { return false },
		},
		{
			fieldname: "designation",
			label: __("Designation"),
			fieldtype: "Data",
			read_only: 1,
			on_change: () => { return false },
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Data",
			read_only: 1,
			on_change: () => { return false },
		},
		{
			fieldname: "show_all_checkins",
			label: __("Show All Checkins"),
			fieldtype: "Check",
		}
	],

	formatter: function(value, row, column, data, default_formatter) {
		var style = {};
		var link;

		if (['attendance_status', 'attendance_abbr'].includes(column.fieldname)) {
			var status = data['attendance_status'];
			var color = data['attendance_color'];

			if (status == "Holiday") {
				style['font-weight'] = 'bold';
			}

			if (color) {
				style['color'] = color;
			}
		}

		if (['working_hours'].includes(column.fieldname)) {
			if (flt(value) > 0) {
				style['color'] = 'blue';
			}
		}

		if (['late_entry_hours', 'early_exit_hours'].includes(column.fieldname)) {
			if (flt(value) > 0) {
				style['color'] = 'orange';
			}
		}

		if (['attendance_status', 'attendance_abbr', 'working_hours'].includes(column.fieldname)) {
			if (data['attendance']) {
				link = "/app/attendance/" + encodeURIComponent(data['attendance']);
			} else if (status != "Holiday") {
				style['opacity'] = '0.8';
			}
		}

		if (column.checkin_idx) {
			var checkin_name = data['checkin_' + column.checkin_idx];
			if (checkin_name) {
				link = "/app/employee-checkin/" + encodeURIComponent(checkin_name);
			}
		}

		return default_formatter(value, row, column, data, {css: style, link_href: link, link_target: "_blank"});
	},

	onload: function (query_report) {
		let employee_user_permissions = frappe.defaults.get_user_permissions()['Employee'];
		if (employee_user_permissions && employee_user_permissions.length == 1) {
			query_report.set_filter_value("employee", employee_user_permissions[0].doc);
		}
	}
}
