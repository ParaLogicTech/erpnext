// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Supplier", {
	setup: function (frm) {
		frm.set_query('default_price_list', { 'buying': 1 });
		if (frm.doc.__islocal == 1) {
			frm.set_value("represents_company", "");
		}
		frm.set_query('account', 'accounts', function (doc, cdt, cdn) {
			var d = locals[cdt][cdn];
			return {
				filters: {
					'account_type': 'Payable',
					'company': d.company,
					"is_group": 0
				}
			}
		});
		frm.set_query('cost_center', 'accounts', function(doc, cdt, cdn) {
			var d  = locals[cdt][cdn];
			var filters = {
				'company': d.company,
				"is_group": 0
			};
			return {
				filters: filters
			}
		});
		frm.set_query("default_bank_account", function() {
			return {
				filters: {
					"is_company_account":1
				}
			}
		});

		frm.set_query('expense_account', function() {
			return {
				filters:[
					['Account', 'is_group', '=', 0],
					['Account', 'account_type', 'in', ['Expense Account', 'Cost of Goods Sold']]
				]
			};
		});
	},
	refresh: function (frm) {
		frappe.dynamic_link = { doc: frm.doc, fieldname: 'name', doctype: 'Supplier' }

		if (frappe.defaults.get_default("supp_master_name") != "Naming Series") {
			frm.toggle_display("naming_series", false);
		} else {
			erpnext.toggle_naming_series();
		}

		if (frm.doc.__islocal) {
			hide_field(['address_html','contact_html']);
			frappe.contacts.clear_address_and_contact(frm);
		}
		else {
			unhide_field(['address_html','contact_html']);
			frappe.contacts.render_address_and_contact(frm);

			// custom buttons
			frm.add_custom_button(__('Accounting Ledger'), function () {
				frappe.set_route('query-report', 'General Ledger', {
					party_type: 'Supplier',
					party: frm.doc.name,
					from_date: frappe.defaults.get_user_default("year_start_date"),
					to_date: frappe.defaults.get_user_default("year_end_date")
				});
			});

			frm.add_custom_button(__('Accounts Payable'), function () {
				frappe.set_route('query-report', 'Accounts Payable', { supplier: frm.doc.name });
			});

			frm.add_custom_button(__('Ledger Summary'), function() {
				frappe.set_route('query-report', 'Supplier Ledger Summary', {
					party: frm.doc.name,
					from_date: frappe.defaults.get_user_default("year_start_date"),
					to_date: frappe.defaults.get_user_default("year_end_date")
				});
			});

			frm.add_custom_button(__('Bank Account'), function () {
				erpnext.utils.make_bank_account(frm.doc.doctype, frm.doc.name);
			}, __('Create'));

			frm.add_custom_button(__('Pricing Rule'), function () {
				erpnext.utils.make_pricing_rule(frm.doc.doctype, frm.doc.name);
			}, __('Create'));

			// indicators
			erpnext.utils.set_party_dashboard_indicators(frm);
		}
	},

	is_internal_supplier: function(frm) {
		if (frm.doc.is_internal_supplier == 1) {
			frm.toggle_reqd("represents_company", true);
		}
		else {
			frm.toggle_reqd("represents_company", false);
		}
	},

	tax_id: function(frm) {
		frappe.regional.pakistan.format_ntn(frm, "tax_id");
	},
	tax_cnic: function(frm) {
		frappe.regional.pakistan.format_cnic(frm, "tax_cnic");
	},
	tax_strn: function(frm) {
		frappe.regional.pakistan.format_strn(frm, "tax_strn");
	},
});
