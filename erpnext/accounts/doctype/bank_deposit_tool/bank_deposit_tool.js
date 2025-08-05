// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bank Deposit Tool", {
	onload: function(frm) {
		frm.disable_save();
	},
	refresh: function(frm) {
		frm.events.set_up_reference_row_selection(frm);
	},
	setup: function(frm) {
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
	},
	get_undeposited_entries: function(frm) {
		if (!frm.doc.undeposited_account) {
			frappe.msgprint(__('Please select an Undeposited Account first.'));
			return;
		}
		frm.events.fetch_undeposited_entries(frm);
	},

	fetch_undeposited_entries: function(frm) {
		frappe.call({
				method: "erpnext.accounts.doctype.bank_deposit_tool.bank_deposit_tool.populate_undeposited_entries",
				args: {
					doc_name: frm.doc,
					undeposited_account: frm.doc.undeposited_account
				},
				callback: function(r) {
					if (r.message) {
						frm.doc.undeposited_entries = r.message.undeposited_entries;
						(frm.doc.undeposited_entries || []).forEach(row => {
							frm.events.fetch_undeposited_details(frm, row.voucher_type, row.voucher_no, row); // Use doctype and name
						});
						frm.refresh_field('undeposited_entries');
					}
				}
			});
	},

	deposit_to_account: function(frm) {
		if (frm.doc.deposit_to_account) {
			frappe.call({
				method: "erpnext.accounts.doctype.bank_deposit_tool.bank_deposit_tool.verify_account_currencies",
				args: {
					source_account: frm.doc.undeposited_account,
					destination_account: frm.doc.deposit_to_account
				},
				callback: function(r) {
					if(!r.message) {
						frappe.msgprint(__("Undeposited Account currency should match the account currency that is being deposited to"));
					}
				}
			});
		}
	},
	create_deposit: function(frm) {
		let selected_rows = frm.fields_dict.undeposited_entries.grid.get_selected_children();
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
		// call the controller to reconcile entries
		frappe.call({
			method: "erpnext.accounts.doctype.bank_deposit_tool.bank_deposit_tool.reconcile_undeposited_entries",
			args: {
				source_account: frm.doc.undeposited_account,
				deposit_account: frm.doc.deposit_to_account,
				selected_entries: selected_rows,
				deduction_entries: JSON.stringify(frm.fields_dict.adjustment_entries.grid.get_data()),
				company: frm.doc.company,
				remark: frm.doc.remarks,
				deposit_date: frm.doc.deposit_date
			},
			callback: function(r) {
				if (!r.exc) {
					frappe.msgprint(__('Deposit Journal Entry created successfully: {0}', [r.message]));
					frm.events.fetch_undeposited_entries(frm);
				}
			}
		});
	},

	set_up_reference_row_selection: frm => {
		frm.fields_dict.undeposited_entries.grid.wrapper.on('click', '.grid-row-check', (e) => {
			frm.events.reconcile_reference_rows(frm);
		});
	},

	reconcile_reference_rows: function(frm) {
		let selected_rows = frm.fields_dict.undeposited_entries.grid.get_selected_children();
		let received_amount = 0;


		selected_rows.forEach((row) => {
			received_amount += row.amount || 0;
		});

		frm.set_value('deposited_amount', received_amount);
		frm.set_value('received_amount', received_amount);

		// Calculate difference
		let difference = 0;
		// verify and reduce the deduction entry amount if there are any
		if (frm.doc.adjustment_entries.length > 0) {
			frm.doc.adjustment_entries.forEach((d_row) => {
				difference -= d_row.adjustment_amount || 0;
			})
		}
		frm.set_value('difference_amount', difference);

//		frm.refresh_field('received_amount');
//		frm.refresh_field('deposited_amount');
//		frm.refresh_field('difference_amount');
	},
	deposited_amount: function(frm) {
		let deposited_amount = frm.doc.deposited_amount;
		if (frm.doc.deposited_amount > frm.doc.received_amount) {
			frappe.msgprint(__('Received amount must be less than paid amount'));
			deposited_amount = frm.doc.received_amount;
		}
		// Calculate difference
		let difference = frm.doc.received_amount - deposited_amount;
		frm.set_value('difference_amount', difference);
		frm.refresh_field('difference_amount');
	},
	reconcile_difference_amount: function(frm) {
		let difference = frm.doc.difference_amount;
		if (frm.doc.adjustment_entries.length > 0) {
			frm.doc.adjustment_entries.forEach((d_row) => {
				difference -= d_row.adjustment_amount || 0;
			})
		}
		frm.set_value('difference_amount', difference);
		frm.refresh_field('difference_amount');
	},
    fetch_undeposited_details: function(frm, cdt, cdn, row) {

		frappe.call({
			method: "erpnext.accounts.doctype.bank_deposit_tool.bank_deposit_tool.get_undeposited_entry_details",
			args: {
				doctype: row.voucher_type,
				docname: row.voucher_no
			},
			callback: function(r) {
				if (!r.exc && r.message) {
					row.party = r.message.party;
					row.party_type = r.message.party_type;
					row.cheque_number = r.message.cheque_number;
					console.log(r.message)
				}
			}
		});
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
		frm.events.reconcile_difference_amount(frm);
	}
});

