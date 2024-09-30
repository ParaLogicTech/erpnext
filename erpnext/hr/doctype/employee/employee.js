// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext.hr");

erpnext.hr.EmployeeController = class EmployeeController extends frappe.ui.form.Controller {
	setup() {
		this.frm.fields_dict.user_id.get_query = function(doc, cdt, cdn) {
			return {
				query: "frappe.core.doctype.user.user.user_query",
				filters: {ignore_user_type: 1}
			}
		}
		this.frm.fields_dict.reports_to.get_query = function(doc, cdt, cdn) {
			return { query: "erpnext.controllers.queries.employee_query"} }
	}

	refresh() {
		var me = this;
		erpnext.hide_company();
		erpnext.toggle_naming_series();
		me.setup_buttons();
	}

	setup_buttons() {
		var me = this;

		if (!me.frm.doc.__islocal) {
			me.frm.add_custom_button(__('Salary Register'), function () {
				frappe.set_route('query-report', 'Salary Register', {
					employee: me.frm.doc.name,
					from_date: frappe.defaults.get_user_default("year_start_date"),
					to_date: frappe.defaults.get_user_default("year_end_date"),
				});
			}, __("View"));

			me.frm.add_custom_button(__('Attendance Sheet'), function () {
				frappe.set_route('query-report', 'Employee Attendance Sheet', {
					employee: me.frm.doc.name,
				});
			}, __("View"));

			me.frm.add_custom_button(__('Checkin Sheet'), function () {
				frappe.set_route('query-report', 'Employee Checkin Sheet', {
					employee: me.frm.doc.name,
				});
			}, __("View"));

			me.frm.add_custom_button(__('Leave Balance'), function () {
				frappe.set_route('query-report', 'Employee Leave Balance', {
					employee: me.frm.doc.name,
				});
			}, __("View"));

			me.frm.add_custom_button(__('Leave Balance Summary'), function () {
				frappe.set_route('query-report', 'Employee Leave Balance Summary', {
					employee: me.frm.doc.name,
				});
			}, __("View"));

			me.frm.add_custom_button(__('Accounting Ledger'), function () {
				frappe.set_route('query-report', 'General Ledger', {
					party_type: 'Employee',
					party: me.frm.doc.name,
					from_date: frappe.defaults.get_user_default("year_start_date"),
					to_date: frappe.defaults.get_user_default("year_end_date")
				});
			}, __("View"));

			me.frm.add_custom_button(__('Accounting Ledger Summary'), function () {
				frappe.set_route('query-report', 'Employee Ledger Summary', {
					party: me.frm.doc.name,
					from_date: frappe.defaults.get_user_default("year_start_date"),
					to_date: frappe.defaults.get_user_default("year_end_date")
				});
			}, __("View"));
		}
	}

	date_of_birth() {
		return cur_frm.call({
			method: "get_retirement_date",
			args: {date_of_birth: this.frm.doc.date_of_birth}
		});
	}

	salutation() {
		if(this.frm.doc.salutation) {
			this.frm.set_value("gender", {
				"Mr": "Male",
				"Ms": "Female"
			}[this.frm.doc.salutation]);
		}
	}
};

frappe.ui.form.on('Employee',{
	setup: function(frm) {
		frm.set_query("leave_policy", function() {
			return {
				"filters": {
					"docstatus": 1
				}
			};
		});
	},
	onload:function(frm) {
		frm.set_query("department", function() {
			return {
				"filters": {
					"company": frm.doc.company,
				}
			};
		});
	},
	prefered_contact_email:function(frm){		
		frm.events.update_contact(frm)		
	},
	personal_email:function(frm){
		frm.events.update_contact(frm)
	},
	company_email:function(frm){
		frm.events.update_contact(frm)
	},
	user_id:function(frm){
		frm.events.update_contact(frm)
	},
	update_contact:function(frm){
		var prefered_email_fieldname = frappe.model.scrub(frm.doc.prefered_contact_email) || 'user_id';
		frm.set_value("prefered_email",
			frm.fields_dict[prefered_email_fieldname].value)
	},
	create_user: function(frm) {
		if (!frm.doc.prefered_email)
		{
			frappe.throw(__("Please enter Preferred Contact Email"))
		}
		frappe.call({
			method: "erpnext.hr.doctype.employee.employee.create_user",
			args: { employee: frm.doc.name, email: frm.doc.prefered_email },
			callback: function(r)
			{
				frm.set_value("user_id", r.message)
			}
		});
	},
	tax_id: function(frm) {
		frappe.regional.pakistan.format_ntn(frm, "tax_id");
	},
	tax_cnic: function(frm) {
		frappe.regional.pakistan.format_cnic(frm, "tax_cnic");
	},
});

cur_frm.cscript = new erpnext.hr.EmployeeController({frm: cur_frm});
