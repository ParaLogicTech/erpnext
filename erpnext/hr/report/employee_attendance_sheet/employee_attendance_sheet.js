// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt


frappe.query_reports["Employee Attendance Sheet"] = {
	"filters": [
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1
		},
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.month_start(),
			"reqd": 1
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.month_end(),
			"reqd": 1
		},
		{
			"fieldname":"employee",
			"label": __("Employee"),
			"fieldtype": "Link",
			"options": "Employee"
		},
		{
			"fieldname":"show_designation",
			"label": __("Show Designation"),
			"fieldtype": "Check",
		}
	],

	formatter: function(value, row, column, data, default_formatter) {
		var style = {};
		var link;

		if (['total_present', 'total_absent', 'total_half_day', 'total_leave', 'total_late_entry', 'total_early_exit'].includes(column.fieldname) && data.employee) {
			link = `/app/query-report/Employee Checkin Sheet?employee=${encodeURIComponent(data.employee)}&from_date=${data.from_date}&to_date=${data.to_date}`;
		}

		if (column.fieldname == 'total_present' && flt(value)) {
			style['color'] = 'green';
		}
		if (['total_absent', 'total_late_deduction', 'total_deduction'].includes(column.fieldname) && flt(value)) {
			style['color'] = 'red';
		}
		if (column.fieldname == 'total_half_day' && flt(value)) {
			style['color'] = 'orange';
		}
		if ((column.fieldname == 'total_leave' || column.leave_type) && flt(value)) {
			if (column.is_lwp) {
				style['color'] = 'red';
			} else {
				style['color'] = 'blue';
			}
		}
		if (column.fieldname == 'total_late_entry' && flt(value)) {
			style['color'] = 'orange';
		}
		if (column.fieldname == 'total_early_exit' && flt(value)) {
			style['color'] = 'orange';
		}

		if (column.date) {
			var attendance_fieldname = "attendance_date_" + column.date;
			var status_fieldname = "status_date_" + column.date;
			var color_fieldname = "color_date_" + column.date;
			var status = data[status_fieldname];
			var color = data[color_fieldname];

			if (data[attendance_fieldname]) {
				link = "/app/attendance/" + encodeURIComponent(data[attendance_fieldname]);
			} else if (status != "Holiday" && !data.is_day_row) {
				style['opacity'] = '0.8';
			}

			if (status == "Holiday") {
				style['font-weight'] = 'bold';
			}

			if (color) {
				style['color'] = color;
			}

			style['font-size'] = '8pt';
			style['line-height'] = '1.6';
			style['letter-spacing'] = "-0.3px";
		}

		return default_formatter(value, row, column, data, {css: style, link_href: link, link_target: "_blank"});
	},

	onload: function(report) {
		if (frappe.model.can_write("Shift Type")) {
			report.page.add_menu_item(__("Update Checkin Shifts"), function () {
				return frappe.call({
					method: "erpnext.hr.doctype.shift_type.shift_type.update_shift_in_logs",
					args: {
						publish_progress: 1
					},
				});
			});
		}
	}
}
