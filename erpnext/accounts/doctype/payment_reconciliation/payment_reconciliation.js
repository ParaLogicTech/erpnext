// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// For license information, please see license.txt

frappe.provide("erpnext.accounts");

erpnext.accounts.PaymentReconciliationController = class PaymentReconciliationController extends (
	frappe.ui.form.Controller
) {
	onload() {
		this.frm.set_query("party_type", () => {
			return {
				filters: {
					name: ["in", Object.keys(frappe.boot.party_account_types)],
				},
			};
		});

		this.frm.set_query("receivable_payable_account", () => {
			let party_account_type = frappe.boot.party_account_types[this.frm.doc.party_type];
			return {
				filters: {
					company: this.frm.doc.company,
					is_group: 0,
					account_type: party_account_type,
					root_type: party_account_type == "Receivable" ? "Asset" : "Liability",
				},
			};
		});

		this.frm.set_query("advance_payment_account", () => {
			let party_account_type = frappe.boot.party_account_types[this.frm.doc.party_type];
			return {
				filters: {
					company: this.frm.doc.company,
					is_group: 0,
					account_type: party_account_type,
					root_type: party_account_type == "Receivable" ? "Liability" : "Asset",
				},
			};
		});

		this.frm.set_query("bank_cash_account", () => {
			return {
				filters: [
					["Account", "company", "=", this.frm.doc.company],
					["Account", "is_group", "=", 0],
					["Account", "account_type", "in", ["Bank", "Cash"]],
				],
			};
		});

		this.frm.set_query("cost_center", () => {
			return {
				filters: {
					company: this.frm.doc.company,
					is_group: 0,
				},
			};
		});
		this.frm.set_query("cost_center", "payments", () => {
			return {
				filters: {
					company: this.frm.doc.company,
					is_group: 0,
				},
			};
		});
		this.frm.set_query("cost_center", "allocation", () => {
			return {
				filters: {
					company: this.frm.doc.company,
					is_group: 0,
				},
			};
		});
	}

	refresh() {
		this.frm.disable_save();

		this.frm.set_df_property("invoices", "cannot_delete_rows", true);
		this.frm.set_df_property("payments", "cannot_delete_rows", true);
		this.frm.set_df_property("allocation", "cannot_delete_rows", true);

		this.frm.set_df_property("invoices", "cannot_add_rows", true);
		this.frm.set_df_property("payments", "cannot_add_rows", true);
		this.frm.set_df_property("allocation", "cannot_add_rows", true);

		erpnext.hide_company(this.frm);

		if (this.frm.doc.receivable_payable_account) {
			this.frm.add_custom_button(__("Get Unreconciled Entries"), () => this.get_unreconciled_entries());
			this.frm.change_custom_button_type(__("Get Unreconciled Entries"), null, "primary");
		}
		if (this.frm.doc.invoices.length && this.frm.doc.payments.length) {
			this.frm.add_custom_button(__("Allocate"), () => this.allocate());
			this.frm.change_custom_button_type(__("Allocate"), null, "primary");
			this.frm.change_custom_button_type(__("Get Unreconciled Entries"), null, "default");
		}
		if (this.frm.doc.allocation.length) {
			this.frm.add_custom_button(__("Reconcile"), () => this.reconcile());
			this.frm.change_custom_button_type(__("Reconcile"), null, "primary");
			this.frm.change_custom_button_type(__("Get Unreconciled Entries"), null, "default");
			this.frm.change_custom_button_type(__("Allocate"), null, "default");
		}
	}

	company() {
		this.frm.set_value("party", "");
		this.frm.set_value("receivable_payable_account", "");
	}

	party_type() {
		this.frm.set_value("party", "");
	}

	party() {
		this.frm.set_value("receivable_payable_account", "");
		this.clear_child_tables();

		if (!this.frm.doc.receivable_payable_account && this.frm.doc.party_type && this.frm.doc.party) {
			frappe.call({
				method: "erpnext.accounts.party.get_party_account",
				args: {
					company: this.frm.doc.company,
					party_type: this.frm.doc.party_type,
					party: this.frm.doc.party,
					include_advance: 1,
				},
				callback: (r) => {
					if (!r.exc && r.message) {
						if (typeof r.message === "string") {
							this.frm.set_value("receivable_payable_account", r.message);
						} else if (Array.isArray(r.message)) {
							this.frm.set_value("receivable_payable_account", r.message[0]);
							this.frm.set_value("advance_payment_account", r.message[1]);
						}
					}
					this.frm.refresh();
				},
			});
		}
	}

	receivable_payable_account() {
		this.clear_child_tables();
		this.frm.refresh();
	}

	invoice_name() {
		this.get_unreconciled_entries();
	}

	payment_name() {
		this.get_unreconciled_entries();
	}

	clear_child_tables() {
		this.frm.clear_table("invoices");
		this.frm.clear_table("payments");
		this.frm.clear_table("allocation");
		this.frm.refresh_fields();
	}

	get_unreconciled_entries() {
		this.frm.clear_table("allocation");
		return this.frm.call({
			doc: this.frm.doc,
			method: "get_unreconciled_entries",
			callback: () => {
				if (!(this.frm.doc.payments.length || this.frm.doc.invoices.length)) {
					frappe.throw({
						message: __("No Unreconciled Invoices and Payments found for this party and account"),
					});
				} else if (!this.frm.doc.invoices.length) {
					frappe.throw({ message: __("No Outstanding Invoices found for this party") });
				} else if (!this.frm.doc.payments.length) {
					frappe.throw({ message: __("No Unreconciled Payments found for this party") });
				}
				this.frm.refresh();
			},
		});
	}

	allocate() {
		let payments = this.frm.fields_dict.payments.grid.get_selected_children();
		if (!payments.length) {
			payments = this.frm.doc.payments;
		}
		let invoices = this.frm.fields_dict.invoices.grid.get_selected_children();
		if (!invoices.length) {
			invoices = this.frm.doc.invoices;
		}
		return this.frm.call({
			doc: this.frm.doc,
			method: "allocate_entries",
			args: {
				payments: payments,
				invoices: invoices,
			},
			callback: () => {
				this.frm.refresh();
			},
		});
	}

	reconcile() {
		let show_difference_dialog = this.frm.doc.allocation.filter((d) => d.difference_amount);

		if (show_difference_dialog && show_difference_dialog.length) {
			this.data = [];
			const dialog = new frappe.ui.Dialog({
				title: __("Select Difference Account"),
				size: "extra-large",
				fields: [
					{
						fieldname: "allocation",
						fieldtype: "Table",
						label: __("Allocation"),
						data: this.data,
						in_place_edit: true,
						cannot_add_rows: true,
						get_data: () => {
							return this.data;
						},
						fields: [
							{
								fieldtype: "Data",
								fieldname: "docname",
								in_list_view: 1,
								hidden: 1,
							},
							{
								fieldtype: "Data",
								fieldname: "reference_type",
								label: __("Voucher Type"),
								in_list_view: 1,
								read_only: 1,
								columns: 1,
							},
							{
								fieldtype: "Dynamic Link",
								fieldname: "reference_name",
								label: __("Voucher No"),
								options: "reference_type",
								in_list_view: 1,
								read_only: 1,
								columns: 2,
							},
							{
								fieldtype: "Date",
								fieldname: "reconciliation_posting_date",
								label: __("Posting Date"),
								in_list_view: 1,
								reqd: 2,
							},
							{
								fieldtype: "Link",
								options: "Account",
								in_list_view: 1,
								label: __("Difference Account"),
								fieldname: "difference_account",
								reqd: 1,
								columns: 3,
								get_query: () => {
									return {
										filters: {
											company: this.frm.doc.company,
											is_group: 0,
										},
									};
								},
							},
							{
								fieldtype: "Currency",
								in_list_view: 1,
								label: __("Difference Amount"),
								fieldname: "difference_amount",
								read_only: 1,
								columns: 2,
							},
						],
					},
				],
				primary_action: () => {
					const args = dialog.get_values()["allocation"];

					args.forEach((d) => {
						frappe.model.set_value(
							"Payment Reconciliation Allocation",
							d.docname,
							"difference_account",
							d.difference_account
						);
						frappe.model.set_value(
							"Payment Reconciliation Allocation",
							d.docname,
							"reconciliation_posting_date",
							d.reconciliation_posting_date
						);
					});

					this.reconcile_payment_entries();
					dialog.hide();
				},
				primary_action_label: __("Reconcile Entries"),
			});

			this.frm.doc.allocation.forEach((d) => {
				if (d.difference_amount) {
					dialog.fields_dict.allocation.df.data.push({
						docname: d.name,
						reference_type: d.reference_type,
						reference_name: d.reference_name,
						difference_amount: d.difference_amount,
						difference_account: d.difference_account,
						reconciliation_posting_date: d.reconciliation_posting_date,
					});
				}
			});

			this.data = dialog.fields_dict.allocation.df.data;
			dialog.fields_dict.allocation.grid.refresh();
			dialog.show();
		} else {
			frappe.confirm(__("Are you sure you want to reconcile the selected entries?"), () => {
				this.reconcile_payment_entries();
			});
		}
	}

	reconcile_payment_entries() {
		return this.frm.call({
			doc: this.frm.doc,
			method: "reconcile",
			callback: () => {
				this.frm.clear_table("allocation");
				this.frm.refresh();
			},
		});
	}

	allocated_amount(doc, cdt, cdn) {
		if (cdt != "Payment Reconciliation Allocation") {
			return;
		}

		let row = frappe.get_doc(cdt, cdn);

		let pay = this.frm.doc.payments.find((x) => (
			x.reference_type == row.reference_type
			&& x.reference_name == row.reference_name
		));

		if (pay) {
			let remaining_amount = flt(pay.amount);
			for (const d of this.frm.doc.allocation || []) {
				remaining_amount = flt(remaining_amount, precision("amount", d));
				if (
					row.reference_type == d.reference_type
					&& row.reference_name == d.reference_name
					&& remaining_amount
				) {
					if (flt(d.allocated_amount) <= remaining_amount) {
						d.amount = remaining_amount;
						remaining_amount -= d.allocated_amount;
					}
				}
			}
		}

		return this.get_difference_amount(row);
	}

	get_difference_amount(row) {
		return frappe.call({
			method: "erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation.calculate_difference_amount",
			args: {
				args: row,
				account: this.frm.doc.receivable_payable_account,
				party_type: this.frm.doc.party_type,
			},
			callback: (r) => {
				frappe.model.set_value(
					row.doctype,
					row.name,
					"difference_amount",
					flt(r.message),
				);
			}
		});
	}
};

extend_cscript(cur_frm.cscript, new erpnext.accounts.PaymentReconciliationController({ frm: cur_frm }));
