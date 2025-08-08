// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bank Deposit Tool", {
	onload: function(frm) {
		frm.disable_save();
	},

	refresh: function(frm) {
		frm.events.set_up_reference_row_selection(frm);
		frm.page.set_secondary_action('Create Deposit', function() {
			frm.events.create_deposit(frm);
		});
		if (!frm.doc.from_date) {
			frm.set_value("from_date", frappe.datetime.month_start());
		}
		if (!frm.doc.to_date) {
			frm.set_value("to_date", frappe.datetime.month_end());
		}
	},

	setup: function(frm) {
		frm.events.setup_filters(frm);
	},

	set_up_reference_row_selection: frm => {
		// reconcile when the row is selected or deselected
		frm.fields_dict.undeposited_entries.grid.wrapper.on('click', '.grid-row-check', (e) => {
			frm.events.reconcile_reference_rows(frm);
		});
	},

	setup_filters: function(frm) {
		frm.set_query("undeposited_account", function() {
			return {
				filters: {
				  root_type: "Asset",
				  is_group: 0,
				  company: frm.doc.company
				}
		  };
		});
		frm.set_query("deposit_to_account", function() {
			return {
				filters: {
					root_type: "Asset",
					is_group: 0,
					company: frm.doc.company
				}
			};
		});
		frm.set_query("account", "adjustment_entries", function(doc, cdt, cdn) {
			return {
				filters: {
					root_type: ["in", ["Income", "Expense"]],
					is_group: 0,
					company: doc.company
				}
			};
		});
	},

	get_undeposited_entries: function(frm) {
		if (!frm.doc.undeposited_account) {
			frappe.msgprint(__('Please select Undeposited Account'));
			return;
		}
		frm.events.fetch_undeposited_entries(frm);
	},

	fetch_undeposited_entries: function(frm) {
		frm.call({
			doc: frm.doc,
			method: 'get_undeposited_entries',
			callback: function(r, rt) {
				frm.refresh_field('undeposited_entries');
				frm.events.set_up_reference_row_selection(frm);
			}
		});
	},

	create_deposit: function(frm) {
		let selected_rows = frm.fields_dict.undeposited_entries.grid.get_selected_children();
		// verify the company has been selected
		if (!frm.doc.company) {
			frappe.msgprint(__('Please select the Company'));
			return;
		}
		// verify the accounts are selected
		if (!frm.doc.undeposited_account || !frm.doc.deposit_to_account) {
			frappe.msgprint(__('Please select Undeposited and Deposit To accounts'));
			return;
		}
		// verify at-least one undeposited entry is selected
		if (!selected_rows.length) {
			frappe.msgprint(__('Please select at least one entry to create deposit.'));
			return;
		}
		// verify the difference amount is zero
		if (frm.doc.difference_amount != 0) {
			frappe.msgprint(__('Cannot create deposit with non zero difference amount.'));
			return;
		}
		// verify the deposit date has been added
		if (!frm.doc.deposit_date) {
			frappe.msgprint(__('Please select Deposit Date'));
			return;
		}
		// verify the deposit number has been added
		if (!frm.doc.deposit_number) {
			frappe.msgprint(__('Please enter deposit number'));
			return;
		}
		// call the controller to reconcile entries
		frm.call({
			doc: frm.doc,
			method: "reconcile_undeposited_entries",
			args: {
			selected_entries: selected_rows
			},
			freeze: true,
			freeze_message: __('Creating Deposit Entry...'),
			callback: function(r) {
				if (!r.exc) {
					frm.events.fetch_undeposited_entries(frm);
				}
			}
		});
	},

	reconcile_reference_rows: function(frm) {
		let selected_rows = frm.fields_dict.undeposited_entries.grid.get_selected_children();
		let selected_deposit_amount = 0;

		selected_rows.forEach((row) => {
			selected_deposit_amount += flt(row.amount) || 0;
		});

		frm.set_value('selected_deposit_amount', selected_deposit_amount);
		frm.set_value('net_deposited_amount', selected_deposit_amount);

		frm.events.recalculate_difference(frm);
	},

	recalculate_difference: function(frm) {
		let received = frm.doc.selected_deposit_amount || 0;
		let deposited = frm.doc.net_deposited_amount || 0;

		let base_difference = received - deposited;
		let total_adjustments = 0;

		if (frm.doc.adjustment_entries?.length) {
			frm.doc.adjustment_entries.forEach(d_row => {
				total_adjustments += flt(d_row.adjustment_amount) || 0;
			});
		}

		let final_difference = base_difference - total_adjustments;
		frm.set_value('difference_amount', final_difference);
		frm.refresh_field('difference_amount');
	},

	net_deposited_amount: function(frm) {
		let deposited_amount = frm.doc.net_deposited_amount;
		if (frm.doc.net_deposited_amount > frm.doc.selected_deposit_amount) {
			frappe.msgprint(__('Net Deposit Amount must be less than the Deposit amount'));
			deposited_amount = frm.doc.selected_deposit_amount;
		}
		frm.events.recalculate_difference(frm);
	},

	// verify filter validations
	to_date: function(frm) {
		if (frm.doc.from_date && frm.doc.to_date) {
			if (frappe.datetime.get_diff(frm.doc.to_date, frm.doc.from_date) < 0) {
				frappe.msgprint(__('To Date cannot be before From Date'));
				frm.set_value('to_date', '');
			}
		}
	},

	// verify the min max validations
	maximum_pending_deposit_entry_amount: function(frm) {
		if (frm.doc.minimum_pending_deposit_entry_amount && frm.doc.maximum_pending_deposit_entry_amount) {
			if (frm.doc.maximum_pending_deposit_entry_amount < frm.doc.minimum_pending_deposit_entry_amount) {
				frappe.msgprint(__('Maximum Amount cannot be less than Minimum Amount'));
				frm.set_value('maximum_pending_deposit_entry_amount', '');
			}
		}
	}
});

frappe.ui.form.on("Deposit Adjustments", {
	adjustment_amount: function(frm, cdt, cdn) {
		let child_row = frappe.get_doc(cdt, cdn);
		let adjustment_value = child_row.adjustment_amount || 0;
		let difference_amount = frm.doc.difference_amount || 0;

		if (adjustment_value > difference_amount) {
			frappe.msgprint({
				message: __("Adjustment Amount cannot be greater than the Difference Amount ({0}). Resetting to zero.", [difference_amount]),
				title: __("Invalid Adjustment Amount"),
				indicator: 'red'
			});
			frappe.model.set_value(cdt, cdn, 'adjustment_amount', 0);
		}
		frm.events.recalculate_difference(frm);
	},
	adjustment_entries_remove: function(frm) {
		frm.events.recalculate_difference(frm);
	}
});

