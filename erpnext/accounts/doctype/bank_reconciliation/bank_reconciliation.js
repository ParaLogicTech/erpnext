// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Bank Reconciliation", {
	setup(frm) {
		frm.events.setup_queries(frm);
		frm.events.setup_amount_formatters(frm);

		frm.set_df_property("payment_entries", "cannot_add_rows", true);
		frm.set_df_property("payment_entries", "cannot_delete_rows", true);
		frm.set_df_property("payment_entries", "disable_sorting", true);

		$(frm.wrapper).on("grid-row-render", (e, grid_row) => {
			frm.events.toggle_highlight(grid_row);
		});

		frm.events.process_route_options(frm);
	},

	process_route_options(frm) {
		if (!frappe.route_options) {
			return;
		}

		if (frappe.route_options.bank_account) {
			frm.doc.bank_account = frappe.route_options.bank_account;
		}
		if (frappe.route_options.from_date) {
			frm.doc.from_date = frappe.route_options.from_date;
		}
		if (frappe.route_options.to_date) {
			frm.doc.to_date = frappe.route_options.to_date;
		}
		if (frappe.route_options.allow_corrections) {
			frm.doc.allow_corrections = cint(frappe.route_options.allow_corrections);
		}

		if (!frm.doc.from_date) {
			frm.set_value("from_date", frappe.datetime.month_start());
		}
		if (!frm.doc.to_date) {
			frm.set_value("to_date", frappe.datetime.month_end());
		}

		if (frm.doc.bank_account && frm.doc.from_date && frm.doc.to_date) {
			frm.events.get_payment_entries(frm);
		}
	},

	set_query_params(frm) {
		let full_url = window.location.href.replace(window.location.search, "");

		let query_params = Object.entries({
			bank_account: frm.doc.bank_account,
			from_date: frm.doc.from_date,
			to_date: frm.doc.to_date,
			allow_corrections: frm.doc.allow_corrections,
		}).map(([field, value]) => `${field}=${encodeURIComponent(cstr(value))}`)
		.filter(Boolean)
		.join("&");

		if (query_params) {
			full_url += "?" + query_params;
		}
		window.history.replaceState(null, null, full_url);
	},

	refresh(frm) {
		erpnext.hide_company(frm);

		frm.disable_save();

		frm.page.set_primary_action(__("Reconcile"), () => {
			frappe.confirm(__("Are you sure you want to reconcile ctatement and update bank clearance?"), () => {
				frm.events.update_clearance(frm);
			});
		});

		frm.page.set_secondary_action(__("Get Payment Entries"), () => {
			frm.events.get_payment_entries(frm);
		});

		frm.add_custom_button(__("Bank Reconciliation Statement"), () => {
			frappe.route_options = {
				bank_account: frm.doc.bank_account,
				from_date: frm.doc.from_date,
				to_date: frm.doc.to_date,
			}
			frappe.open_in_new_tab = true;
			frappe.set_route("query-report", "Bank Reconciliation Statement");
		}, __("Report"));
	},

	onload(frm) {
		frm.fields_dict.sec_summary.wrapper.addClass("banking-sticky-section");
	},

	onload_post_render(frm) {
		frm.events.setup_row_checkbox_selection(frm);
	},

	setup_queries(frm) {
		frm.set_query("bank_account", () => {
			return {
				filters: {
					"company": frm.doc.company,
					"is_company_account": 1,
				}
			};
		});

		frm.set_query("account", () => {
			return {
				filters: {
					"company": frm.doc.company,
					"account_type": ["in", ["Bank", "Cash"]],
					"is_group": 0
				}
			};
		});

		frm.set_query("suspense_account", () => {
			return {
				filters: {
					"company": frm.doc.company,
					"account_type": ["in", ["Bank", "Cash"]],
					"is_group": 0
				}
			};
		});
	},

	setup_amount_formatters(frm) {
		let cleared_amount_df = frappe.meta.get_docfield("Bank Reconciliation", "cleared_amount");
		let cleared_incoming_df = frappe.meta.get_docfield("Bank Reconciliation", "cleared_incoming");
		let cleared_outgoing_df = frappe.meta.get_docfield("Bank Reconciliation", "cleared_outgoing");
		let difference_df = frappe.meta.get_docfield("Bank Reconciliation", "difference");
		let row_amount_df = frappe.meta.get_docfield("Bank Reconciliation Detail", "amount");

		cleared_amount_df.formatter = (value, df, options, doc) => {
			return erpnext.utils.banking_amount_formatter(value, df, options, doc);
		}
		cleared_incoming_df.formatter = (value, df, options, doc) => {
			return erpnext.utils.banking_amount_formatter(value, df, options, doc, "var(--green-800)");
		}
		cleared_outgoing_df.formatter = (value, df, options, doc) => {
			return erpnext.utils.banking_amount_formatter(value, df, options, doc, "var(--red-700)");
		}
		difference_df.formatter = (value, df, options, doc) => {
			return erpnext.utils.banking_amount_formatter(value, df, options, doc, "var(--red-700)", "var(--green-800)");
		}
		row_amount_df.formatter = (value, df, options, doc) => {
			return erpnext.utils.banking_amount_formatter(value, df, options, doc);
		}
	},

	setup_row_checkbox_selection(frm) {
		// reconcile when the row is selected or deselected
		frm.fields_dict.payment_entries.grid.wrapper.on('click', '.grid-row-check', (e) => {
			const $check = $(e.currentTarget);
			const is_select_all = $check.parents(".grid-heading-row:first").length !== 0;
			const docname = $check.parents(".grid-row:first")?.attr("data-name");
			const grid_row = docname ? frm.fields_dict.payment_entries.grid.get_row(docname) : null;
			if (is_select_all) {
				for (let d of frm.fields_dict.payment_entries.grid.grid_rows) {
					frm.events.on_row_check(frm, d);
				}
			} else if (grid_row) {
				frm.events.on_row_check(frm, grid_row);
			}

			frm.events.calculate_totals(frm);
		});
	},

	toggle_highlight(grid_row) {
		if (!grid_row || !grid_row.doc || grid_row.doc.doctype !== "Bank Reconciliation Detail") {
			return;
		}
		grid_row.row.toggleClass("highlight", Boolean(grid_row.doc && grid_row.doc.clearance_date));
	},

	on_row_check(frm, grid_row) {
		if (!grid_row || !grid_row.doc || grid_row.doc.doctype !== "Bank Reconciliation Detail") {
			return;
		}

		grid_row.doc.clearance_date = grid_row.doc.__checked ? frm.doc.to_date : null;
		refresh_field("clearance_date", grid_row.doc.name, grid_row.doc.parentfield);
		frm.events.toggle_highlight(grid_row);
	},

	from_date(frm) {
		frm.events.get_opening_balance(frm);
	},

	bank_account(frm) {
		frm.events.get_opening_balance(frm);
		frm.events.get_last_clearance_date(frm);
	},

	opening_balance(frm) {
		frm.events.calculate_totals(frm);
	},

	closing_balance(frm) {
		frm.events.calculate_totals(frm);
	},

	calculate_totals(frm) {
		frm.doc.uncleared_amount = 0;
		frm.doc.cleared_amount = 0;
		frm.doc.cleared_incoming = 0;
		frm.doc.cleared_outgoing = 0;

		for (let d of frm.doc.payment_entries || []) {
			if (d.clearance_date) {
				frm.doc.cleared_amount += flt(d.amount);

				if (flt(d.amount) < 0) {
					frm.doc.cleared_outgoing -= flt(d.amount);
				} else {
					frm.doc.cleared_incoming += flt(d.amount);
				}
			} else {
				frm.doc.uncleared_amount += flt(d.amount);
			}
		}

		frm.doc.difference = flt(frm.doc.closing_balance) - flt(frm.doc.opening_balance) - flt(frm.doc.cleared_amount);

		frm.refresh_field("uncleared_amount");
		frm.refresh_field("cleared_amount");
		frm.refresh_field("cleared_incoming");
		frm.refresh_field("cleared_outgoing");
		frm.refresh_field("difference");
	},

	get_opening_balance(frm) {
		if (frm.doc.bank_account && frm.doc.from_date) {
			return frappe.call({
				method: "erpnext.accounts.doctype.bank_reconciliation.bank_reconciliation.get_opening_balance",
				args: {
					bank_account: frm.doc.bank_account,
					from_date: frm.doc.from_date,
				},
				callback: (r) => {
					frm.set_value("opening_balance", flt(r.message));
				}
			});
		} else {
			frm.set_value("opening_balance", 0);
		}
	},

	get_last_clearance_date(frm) {
		if (frm.doc.bank_account) {
			return frappe.call({
				method: "erpnext.accounts.doctype.bank_reconciliation.bank_reconciliation.get_last_clearance_date",
				args: {
					bank_account: frm.doc.bank_account,
				},
				callback: (r) => {
					frm.set_value("last_clearance_date", r.message || null);
				}
			});
		} else {
			frm.set_value("last_clearance_date", null);
		}
	},

	update_clearance(frm) {
		return frm.call({
			method: "update_clearance",
			doc: frm.doc,
			freeze: 1,
			freeze_message: __("Reconciling..."),
			callback: (r) => {
				frm.events.reset_checked(frm);
				frm.events.calculate_totals(frm);
				frm.refresh_fields();
			}
		});
	},

	get_payment_entries(frm) {
		let prev_voucher_clearance_dates = frm.events.get_voucher_clearance_dates(frm);

		return frm.call({
			method: "set_payment_entries",
			doc: frm.doc,
			freeze: 1,
			freeze_message: __("Loading Unreconciled Entries..."),
			callback: (r) => {
				if (!frm.doc.allow_corrections) {
					frm.events.set_voucher_clearance_dates(frm, prev_voucher_clearance_dates);
				}
				frm.events.reset_checked(frm);
				frm.events.calculate_totals(frm);
				frm.events.set_query_params(frm);
				frm.refresh_fields();
			}
		});
	},

	reset_checked(frm) {
		for (let d of frm.doc.payment_entries || []) {
			d.__checked = d.clearance_date ? 1 : 0;
		}
	},

	refresh_checkbox(grid_row) {
		if (grid_row) {
			grid_row.select(Boolean(grid_row.doc.clearance_date));
			grid_row.refresh_check();
		}
	},

	set_voucher_clearance_dates(frm, voucher_clearance_dates) {
		for (let row of frm.doc.payment_entries || []) {
			let key = JSON.stringify([
				row.voucher_type,
				row.voucher_no,
				row.voucher_detail_dt || null,
				row.voucher_detail_dn || null,
			]);

			if (voucher_clearance_dates[key]) {
				row.clearance_date = voucher_clearance_dates[key];
			} else {
				row.clearance_date = null;
			}
		}

		frm.refresh_field("payment_entries");
	},

	get_voucher_clearance_dates(frm) {
		let voucher_clearance_dates = {};
		for (let d of frm.doc.payment_entries || []) {
			if (!d.clearance_date) {
				continue;
			}

			let key = JSON.stringify([
				d.voucher_type,
				d.voucher_no,
				d.voucher_detail_dt || null,
				d.voucher_detail_dn || null,
			]);

			voucher_clearance_dates[key] = d.clearance_date;
		}

		return voucher_clearance_dates;
	},
});

frappe.ui.form.on("Bank Reconciliation Detail", {
	clearance_date(frm, cdt, cdn) {
		let grid_row = frm.fields_dict.payment_entries.grid.get_row(cdn || "");
		if (grid_row) {
			frm.events.toggle_highlight(grid_row);
			frm.events.refresh_checkbox(grid_row);
		}
		frm.events.calculate_totals(frm);
	},
});
