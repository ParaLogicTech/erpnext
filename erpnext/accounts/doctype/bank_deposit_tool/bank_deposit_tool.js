// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bank Deposit Tool", {
	setup: function(frm) {
		frm.events.setup_filters(frm);
	},

	refresh: function(frm) {
		erpnext.hide_company(frm);
		if (!frm.doc.company) {
			frm.set_value("company", frappe.defaults.get_user_default("Company"));
		}

		frm.disable_save();

		frm.page.set_primary_action(__("Submit Deposit Entry"), () => {
			frappe.confirm(__("Are you sure you want to submit a Deposit Entry?"), () => {
				frm.events.submit_deposit_entry(frm);
			});
		});

		frm.page.set_secondary_action(__("Draft Deposit Entry"), () => {
			frappe.confirm(__("Are you sure you want to draft a Deposit Entry?"), () => {
				frm.events.make_deposit_entry(frm);
			});
		});

		frm.set_df_property("undeposited_entries", "cannot_add_rows", true);

		frm.events.get_other_company_accounts_and_cost_centers(frm);
	},

	onload_post_render: function (frm) {
		frm.events.setup_row_checkbox_selection(frm);
	},

	setup_filters: function(frm) {
		frm.set_query("undeposited_account", function() {
			return {
				filters: {
					account_type: ["in", ["Bank", "Cash"]],
					company: frm.doc.company,
					is_group: 0,
				}
			};
		});

		frm.set_query("deposit_to_account", function() {
			return {
				filters: {
					account_type: "Bank",
					company: frm.doc.company,
					is_group: 0,
				}
			};
		});

		frm.set_query("account", "adjustment_entries", function(doc, cdt, cdn) {
			return {
				filters: {
					company: doc.company,
					is_group: 0,
				}
			};
		});

		frm.set_query("cost_center", () => {
			return {
				filters: {
					company: frm.doc.company,
					is_group: 0
				}
			};
		});

		frm.set_query("cost_center", "adjustment_entries", () => {
			return {
				filters: {
					company: frm.doc.company,
					is_group: 0
				}
			};
		});
	},

	setup_row_checkbox_selection: function(frm) {
		// reconcile when the row is selected or deselected
		frm.fields_dict.undeposited_entries.grid.wrapper.on('click', '.grid-row-check', (e) => {
			frm.doc.actual_deposit_amount = frm.events.get_selected_deposit_amount(frm);
			frm.events.calculate_totals(frm);
		});
	},

	company: function (frm) {
		frm.events.get_other_company_accounts_and_cost_centers(frm);
	},

	undeposited_account: function (frm) {
		frm.events.get_undeposited_entries(frm);
	},

	deposit_date: function (frm) {
		frm.events.get_undeposited_entries(frm);
	},

	from_date: function (frm) {
		frm.events.get_undeposited_entries(frm);
	},

	to_date: function (frm) {
		frm.events.get_undeposited_entries(frm);
	},

	min_amount: function (frm) {
		frm.events.get_undeposited_entries(frm);
	},

	max_amount: function (frm) {
		frm.events.get_undeposited_entries(frm);
	},

	mode_of_payment: function (frm) {
		frm.events.get_undeposited_entries(frm);
	},

	actual_deposit_amount: function(frm) {
		frm.events.calculate_totals(frm);
	},

	calculate_totals: function(frm) {
		frm.doc.selected_deposit_amount = frm.events.get_selected_deposit_amount(frm);

		let base_difference = flt(frm.doc.selected_deposit_amount) - flt(frm.doc.actual_deposit_amount);

		let total_adjustments = 0;
		for (let d of frm.doc.adjustment_entries || []) {
			total_adjustments += flt(d.adjustment_amount) || 0;
		}

		let final_difference = base_difference - total_adjustments;
		frm.doc.difference_amount = final_difference;
		frm.refresh_fields();
	},

	get_selected_deposit_amount: function(frm) {
		let selected_rows = frm.fields_dict.undeposited_entries.grid.get_selected_children();

		let selected_deposit_amount = 0;
		for (let d of selected_rows || []) {
			selected_deposit_amount += flt(d.amount);
		}

		return selected_deposit_amount;
	},

	reload_undeposited_entries: function (frm) {
		if (!frm.doc.undeposited_account || !frm.doc.deposit_date) {
			frappe.msgprint(__("Please select Undeposited Funds Account and Deposit Date"));
			return;
		}
		frm.events.get_undeposited_entries(frm);
	},

	get_undeposited_entries: function(frm) {
		if (!frm.doc.undeposited_account || !frm.doc.deposit_date) {
			return;
		}

		return frm.call({
			doc: frm.doc,
			method: 'get_undeposited_entries',
			freeze: true,
			freeze_message: __("Loading Undeposited Entries"),
			callback: function() {
				frm.events.calculate_totals(frm);
			}
		});
	},

	submit_deposit_entry: function(frm) {
		let selected_row_names = frm.fields_dict.undeposited_entries.grid.get_selected();
		return frm.call({
			doc: frm.doc,
			method: "submit_deposit_entry",
			args: {
				selected_row_names: selected_row_names
			},
			freeze: true,
			freeze_message: __('Submitting Deposit Entry...'),
			callback: (r) => {
				if (r.message) {
					frappe.set_route("Form", "Journal Entry", r.message);
				}
			}
		});
	},

	make_deposit_entry: function(frm) {
		let selected_row_names = frm.fields_dict.undeposited_entries.grid.get_selected();
		return frm.call({
			doc: frm.doc,
			method: "make_deposit_entry",
			args: {
				selected_row_names: selected_row_names
			},
			freeze: true,
			freeze_message: __('Making Deposit Entry...'),
			callback: (r) => {
				if (r.message) {
					frappe.model.sync(r.message);
					frappe.set_route("Form", r.message.doctype, r.message.name);
				}
			}
		});
	},

	get_other_company_accounts_and_cost_centers: function (frm) {
		if (!frm.doc.company) {
			return;
		}

		let accounts = [];
		let cost_centers = [];

		if (frm.doc.cost_center) {
			cost_centers.push(frm.doc.cost_center);
		}

		if (frm.doc.undeposited_account) {
			accounts.push(frm.doc.undeposited_account);
		}
		if (frm.doc.deposit_to_account) {
			accounts.push(frm.doc.deposit_to_account);
		}

		for (let d of frm.doc.adjustment_entries || []) {
			if (d.account) {
				accounts.push(d.account);
			}
			if (d.cost_center) {
				cost_centers.push(d.cost_center);
			}
		}

		return frappe.call({
			method: "erpnext.accounts.doctype.journal_entry.journal_entry.get_other_company_accounts_and_cost_centers",
			args: {
				target_company: frm.doc.company,
				accounts: accounts,
				cost_centers: cost_centers,
			},
			callback: (r) => {
				if (r.message) {
					frm.set_value(
						"cost_center",
						r.message.cost_centers[frm.doc.cost_center] || r.message.default_cost_center
					);

					if (frm.doc.undeposited_account && r.message.accounts[frm.doc.undeposited_account]) {
						frm.set_value("undeposited_account", r.message.accounts[frm.doc.undeposited_account]);
					}
					if (frm.doc.deposit_to_account && r.message.accounts[frm.doc.deposit_to_account]) {
						frm.set_value("deposit_to_account", r.message.accounts[frm.doc.deposit_to_account]);
					}

					for (let d of frm.doc.adjustment_entries || []) {
						if (d.account && r.message.accounts[d.account]) {
							frappe.model.set_value(d.doctype, d.name, "account", r.message.accounts[d.account]);
						}
						if (d.cost_center && r.message.cost_centers[d.cost_center]) {
							frappe.model.set_value(d.doctype, d.name, "cost_center", r.message.cost_centers[d.cost_center]);
						}
					}
				}
			}
		});
	},
});

frappe.ui.form.on("Bank Deposit Adjustment", {
	supplier: function(frm, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		if (row.supplier && frm.doc.company) {
			return frappe.call({
				method: "erpnext.accounts.party.get_party_account",
				args: {
					company: frm.doc.company,
					party_type: "Supplier",
					party: row.supplier,
				},
				callback: function(r) {
					if (r.message) {
						frappe.model.set_value(row.doctype, row.name, "account", r.message);
					}
				}
			});
		}
	},

	adjustment_amount: function(frm) {
		frm.events.calculate_totals(frm);
	},
	adjustment_entries_remove: function(frm) {
		frm.events.calculate_totals(frm);
	},
});
