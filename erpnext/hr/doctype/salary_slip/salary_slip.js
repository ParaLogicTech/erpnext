// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

cur_frm.add_fetch('employee', 'company', 'company');
cur_frm.add_fetch('time_sheet', 'total_hours', 'working_hours');

frappe.ui.form.on("Salary Slip", {
	setup: function(frm) {
		$.each(["earnings", "deductions"], function(i, table_fieldname) {
			frm.get_field(table_fieldname).grid.editable_fields = [
				{fieldname: 'salary_component', columns: 6},
				{fieldname: 'amount', columns: 4}
			];
		});

		frm.fields_dict["timesheets"].grid.get_field("time_sheet").get_query = function(){
			return {
				filters: {
					employee: frm.doc.employee
				}
			}
		};

		frm.set_query("salary_component", "earnings", function() {
			return {
				filters: {
					type: "earning"
				}
			}
		});

		frm.set_query("salary_component", "deductions", function() {
			return {
				filters: {
					type: "deduction"
				}
			}
		});

		frm.set_query("employee", function() {
			return{
				query: "erpnext.controllers.queries.employee_query"
			}
		});
	},

	start_date: function(frm){
		if(frm.doc.start_date){
			frm.trigger("set_end_date");
		}
	},

	end_date: function(frm) {
		frm.events.get_emp_and_leave_details(frm);
	},

	set_end_date: function(frm){
		frappe.call({
			method: 'erpnext.hr.doctype.payroll_entry.payroll_entry.get_end_date',
			args: {
				frequency: frm.doc.payroll_frequency,
				start_date: frm.doc.start_date
			},
			callback: function (r) {
				if (r.message) {
					frm.set_value('end_date', r.message.end_date);
				}
			}
		})
	},

	company: function(frm) {
		var company = locals[':Company'][frm.doc.company];
		if(!frm.doc.letter_head && company.default_letter_head) {
			frm.set_value('letter_head', company.default_letter_head);
		}
	},

	refresh: function(frm) {
		erpnext.hide_company();
		frm.trigger("toggle_fields")

		var salary_detail_fields = ["formula", "abbr", "statistical_component", "variable_based_on_taxable_salary"];
		cur_frm.fields_dict['earnings'].grid.set_column_disp(salary_detail_fields,false);
		cur_frm.fields_dict['deductions'].grid.set_column_disp(salary_detail_fields,false);

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__('Update Salary Slip'), function () {
				frm.save();
			});
		}
	},

	salary_slip_based_on_timesheet: function(frm) {
		frm.trigger("toggle_fields");
		frm.events.get_emp_and_leave_details(frm);
	},

	payroll_frequency: function(frm) {
		frm.trigger('set_start_end_dates');
	},

	employee: function(frm) {
		frm.events.get_emp_and_leave_details(frm);
	},

	posting_date: function(frm){
		frm.trigger('set_start_end_dates');
	},

	set_start_end_dates: function (frm) {
		if (!frm.doc.salary_slip_based_on_timesheet) {
			frappe.call({
				method: 'erpnext.hr.doctype.payroll_entry.payroll_entry.get_start_end_dates',
				args: {
					payroll_frequency: frm.doc.payroll_frequency,
					start_date: frm.doc.posting_date
				},
				callback: function (r) {
					if (r.message) {
						frm.set_value('start_date', r.message.start_date);
						frm.set_value('end_date', r.message.end_date);
					}
				}
			});
		}
	},

	leave_without_pay: function(frm){
		if (frm.doc.employee && frm.doc.start_date && frm.doc.end_date) {
			return frm.call({
				method: 'process_salary_based_on_leave',
				doc: frm.doc,
				args: {
					"lwp": frm.doc.leave_without_pay,
					"late_days": frm.doc.late_days,
				},
				callback: function(r, rt) {
					frm.dirty();
					frm.refresh();
				}
			});
		}
	},

	late_days: function (frm) {
		frm.trigger('leave_without_pay');
	},

	set_lwp_manually: function (frm) {
		frm.trigger("toggle_fields");
		if (!frm.doc.set_lwp_manually) {
			frm.trigger('leave_without_pay');
		}
	},

	toggle_fields: function(frm) {
		frm.toggle_display(['hourly_wages', 'timesheets'], cint(frm.doc.salary_slip_based_on_timesheet)===1);

		frm.set_df_property('leave_without_pay', 'read_only', cint(frm.doc.set_lwp_manually) ? 0 : 1);
		frm.set_df_property('late_days', 'read_only', cint(frm.doc.set_lwp_manually) ? 0 : 1);

		frm.set_df_property('bank_amount', 'read_only', cint(frm.doc.salary_mode == "Bank"));
		frm.set_df_property('cheque_amount', 'read_only', cint(frm.doc.salary_mode == "Cheque"));
		frm.set_df_property('cash_amount', 'read_only', cint(frm.doc.salary_mode == "Cash"));
	},

	get_emp_and_leave_details: function(frm) {
		return frappe.call({
			method: 'get_emp_and_leave_details',
			doc: frm.doc,
			callback: function(r, rt) {
				frm.dirty();
				frm.refresh();
			}
		});
	},

	bank_amount: function (frm) {
		frm.events.calculate_mode_of_payment(frm);
	},

	cheque_amount: function (frm) {
		frm.events.calculate_mode_of_payment(frm);
	},

	cash_amount: function (frm) {
		frm.events.calculate_mode_of_payment(frm);
	},

	calculate_mode_of_payment: function (frm) {
		return frappe.call({
			method: 'calculate_mode_of_payment',
			doc: frm.doc,
			callback: function(r, rt) {
				frm.dirty();
				frm.refresh();
			}
		});
	}
})

frappe.ui.form.on('Salary Slip Timesheet', {
	time_sheet: function(frm, dt, dn) {
		total_work_hours(frm, dt, dn);
	},
	timesheets_remove: function(frm, dt, dn) {
		total_work_hours(frm, dt, dn);
	}
});

// calculate total working hours, earnings based on hourly wages and totals
var total_work_hours = function(frm, dt, dn) {
	var total_working_hours = 0.0;
	$.each(frm.doc["timesheets"] || [], function(i, timesheet) {
		total_working_hours += timesheet.working_hours;
	});
	frm.set_value('total_working_hours', total_working_hours);

	var wages_amount = frm.doc.total_working_hours * frm.doc.hour_rate;

	frappe.db.get_value('Salary Structure', {'name': frm.doc.salary_structure}, 'salary_component', (r) => {
		var gross_pay = 0.0;
		$.each(frm.doc["earnings"], function(i, earning) {
			if (earning.salary_component == r.salary_component) {
				earning.amount = wages_amount;
				frm.refresh_fields('earnings');
			}
			gross_pay += earning.amount;
		});
		frm.set_value('gross_pay', gross_pay);

		frm.doc.net_pay = flt(frm.doc.gross_pay) - flt(frm.doc.total_deduction);
		frm.doc.rounded_total = Math.round(frm.doc.net_pay);
		refresh_many(['net_pay', 'rounded_total']);
	});
}
