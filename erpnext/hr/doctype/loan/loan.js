// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

{% include 'erpnext/hr/loan_common.js' %};

frappe.ui.form.on('Loan', {
	onload: function (frm) {
		frm.set_query("loan_application", function () {
			return {
				"filters": {
					"applicant": frm.doc.applicant,
					"docstatus": 1,
					"status": "Approved"
				}
			};
		});

		frm.set_query("interest_income_account", function () {
			return {
				"filters": {
					"company": frm.doc.company,
					"root_type": "Income",
					"is_group": 0
				}
			};
		});

		frm.set_query("loan_account", function () {
			return {
				"filters": {
					"company": frm.doc.company,
					"root_type": "Asset",
					"is_group": 0,
					"account_type": ["in", ["Receivable", "Payable"]]
				}
			};
		});

		frm.set_query("payment_account", function () {
			return {
				"filters": {
					"company": frm.doc.company,
					"is_group": 0,
					"account_type": ["in", ['Bank', 'Cash']]
				}
			};
		});
	},

	refresh: function (frm) {
		erpnext.hide_company();
		if (frm.doc.docstatus == 1) {
			if (frm.doc.status == "Sanctioned") {
				frm.add_custom_button(__('Create Disbursement Entry'), function() {
					frm.trigger("make_jv");
				}).addClass("btn-primary");
			} else if (frm.doc.status == "Disbursed" && frm.doc.repayment_start_date) {
				frm.add_custom_button(__('Create Repayment Entry'), function() {
					frm.trigger("make_repayment_entry");
				}).addClass("btn-primary");
			}
		}
		frm.trigger("toggle_fields");
	},

	make_jv: function (frm) {
		frappe.call({
			args: {
				"loan": frm.doc.name,
				"company": frm.doc.company,
				"loan_account": frm.doc.loan_account,
				"applicant_type": frm.doc.applicant_type,
				"applicant": frm.doc.applicant,
				"loan_amount": frm.doc.loan_amount,
				"payment_account": frm.doc.payment_account
			},
			method: "erpnext.hr.doctype.loan.loan.make_jv_entry",
			callback: function (r) {
				if (r.message)
					var doc = frappe.model.sync(r.message)[0];
				frappe.set_route("Form", doc.doctype, doc.name);
			}
		})
	},
	make_repayment_entry: function(frm) {
		let doc = {
			repayment_data: [],
		};

		let fields = [{
			fieldname: 'payments',
			fieldtype: 'Table',
			in_place_edit: true,
			cannot_add_rows: true,
			read_only: 1,
			data: doc.repayment_data,
			fields: [
				{
					fieldtype: 'Date',
					fieldname: 'payment_date',
					label: __('Repayment Date'),
					read_only: 1,
					in_list_view: 1,
					columns: 2
				},
				{
					fieldtype: 'Currency',
					fieldname: 'principal_amount',
					label: __('Principal Amount'),
					read_only: 1,
					in_list_view: 1,
					columns: 3
				},
				{
					fieldtype: 'Currency',
					fieldname: 'interest_amount',
					label: __('Interest'),
					read_only: 1,
					in_list_view: 1,
					columns: 2
				},
				{
					fieldtype: 'Currency',
					read_only: 1,
					fieldname: 'total_payment',
					label: __('Total Payment'),
					in_list_view: 1,
					columns: 3
				},
			],
		}];

		let dialog = new frappe.ui.Dialog({
			title: __("Select Repayment Schedule"), fields: fields, doc: doc, size: "large",
		});

		if (frm.doc['repayment_schedule']) {
			frm.doc['repayment_schedule'].forEach((payment, index) => {
			if (!payment.paid) {
					doc.repayment_data.push({
						'id': index,
						'name': payment.name,
						'payment_date': payment.payment_date,
						'principal_amount': payment.principal_amount,
						'interest_amount': payment.interest_amount,
						'total_payment': payment.total_payment
					});
					dialog.fields_dict.payments.grid.refresh();
				}
			})
		}

		dialog.show();
		dialog.set_primary_action(__('Create Repayment Entry'), function() {
			let values = dialog.get_values();
			if (values) {
				_make_repayment_entry(frm, dialog.fields_dict.payments.grid.get_selected_children());
				dialog.hide()
			}
		});
	},

	mode_of_payment: function (frm) {
		if (frm.doc.mode_of_payment && frm.doc.company) {
			frappe.call({
				method: "erpnext.accounts.doctype.sales_invoice.sales_invoice.get_bank_cash_account",
				args: {
					"mode_of_payment": frm.doc.mode_of_payment,
					"company": frm.doc.company
				},
				callback: function (r, rt) {
					if (r.message) {
						frm.set_value("payment_account", r.message.account);
					}
				}
			});
		}
	},

	loan_application: function (frm) {
	    if(frm.doc.loan_application){
            return frappe.call({
                method: "erpnext.hr.doctype.loan.loan.get_loan_application",
                args: {
                    "loan_application": frm.doc.loan_application
                },
                callback: function (r) {
                    if (!r.exc && r.message) {
                        frm.set_value("loan_type", r.message.loan_type);
                        frm.set_value("loan_amount", r.message.loan_amount);
                        frm.set_value("repayment_method", r.message.repayment_method);
                        frm.set_value("monthly_repayment_amount", r.message.repayment_amount);
                        frm.set_value("repayment_periods", r.message.repayment_periods);
                        frm.set_value("rate_of_interest", r.message.rate_of_interest);
                    }
                }
            });
        }
	},

	repayment_method: function (frm) {
		frm.trigger("toggle_fields")
	},

	toggle_fields: function (frm) {
		frm.toggle_enable("monthly_repayment_amount", frm.doc.repayment_method == "Repay Fixed Amount per Period")
		frm.toggle_enable("repayment_periods", frm.doc.repayment_method == "Repay Over Number of Periods")
	},

	repayment_schedule_remove: function (frm) {
		frm.events.update_repayment_schedule(frm);
	},

	update_repayment_schedule: function (frm) {
		frm.call({
			method: "update_repayment_schedule",
			doc: frm.doc,
			callback: function(r) {
				if(!r.exc){
					frm.refresh_fields();
				}
			}
		});
	},
});

frappe.ui.form.on('Repayment Schedule', {
	principal_amount: function (frm, cdt, cdn) {
		frm.events.update_repayment_schedule(frm);
	},
	payment_date: function (frm, cdt, cdn) {
		frm.events.update_repayment_schedule(frm);
	},

	before_repayment_schedule_remove: function(frm, cdt, cdn) {
		var row = frappe.get_doc(cdt, cdn);
		if(row.paid) {
			frappe.msgprint(__("Cannot remove an already paid repayment schedule"));
			throw "Cannot remove already paid repayment schedule";
		}
	},
})

var _make_repayment_entry = function(frm, payment_rows) {
	frappe.call({
		method: "erpnext.hr.doctype.loan.loan.make_repayment_entry",
		args: {
			payment_rows: payment_rows,
			"loan": frm.doc.name,
			"company": frm.doc.company,
			"loan_account": frm.doc.loan_account,
			"applicant_type": frm.doc.applicant_type,
			"applicant": frm.doc.applicant,
			"payment_account": frm.doc.payment_account,
			"interest_income_account": frm.doc.interest_income_account
		},
		callback: function(r) {
			if (r.message)
				var doc = frappe.model.sync(r.message)[0];
			frappe.set_route("Form", doc.doctype, doc.name, {'payment_rows': payment_rows});
		}
	});
}