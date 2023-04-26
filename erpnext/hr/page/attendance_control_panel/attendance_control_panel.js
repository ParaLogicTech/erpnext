frappe.pages['attendance-control-panel'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Attendance Control Panel',
		single_column: true,
		card_layout: true,
	});

	page.company_field = page.add_field({
		fieldname: 'company',
		label: __('Company'),
		fieldtype: 'Link',
		options: 'Company',
		reqd: 1,
		default: frappe.defaults.get_user_default("Company"),
		change: function() {
			$(page.parent).trigger("reload-attendance");
		}
	});

	page.year_field = page.add_field({
		fieldname: 'year',
		label: __('Year'),
		fieldtype: 'Select',
		change: function() {
			$(page.parent).trigger("reload-attendance");
		},
		reqd: 1,
	});

	page.month_field = page.add_field({
		fieldname: 'month',
		label: __('Month'),
		fieldtype:'Select',
		options: "Jan\nFeb\nMar\nApr\nMay\nJun\nJul\nAug\nSep\nOct\nNov\nDec",
		reqd: 1,
		default: moment(frappe.datetime.get_today()).format("MMM"),
		change: function() {
			$(page.parent).trigger("reload-attendance");
		}
	});

	page.employee_field = page.add_field({
		fieldname: 'employee',
		label: __('Employee'),
		fieldtype: 'Link',
		options: 'Employee',
		change: function() {
			$(page.parent).trigger("reload-attendance");
		}
	});

	setup_year_field_options(page);

	$(wrapper).bind("show", function () {
		$(page.main).append("<div class='attendance-control-panel'></div>");
		frappe.require("attendance_control_panel.bundle.js");
	});
}

function setup_year_field_options(page) {
	frappe.call({
		method: "erpnext.hr.report.monthly_attendance_sheet.monthly_attendance_sheet.get_attendance_years",
		callback: function(r) {
			var year_filter = page.year_field;
			year_filter.df.options = r.message;

			var previous_month = frappe.datetime.str_to_obj(frappe.datetime.add_months(frappe.datetime.get_today(), -1));
			year_filter.df.default = previous_month.getFullYear();

			year_filter.refresh();
			year_filter.set_input(year_filter.df.default);
		}
	});
}
