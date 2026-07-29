// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bank Deposit Tool", {
	setup(frm) {
		frm.events.setup_queries(frm);
		frm.events.setup_amount_formatters(frm);

		frm.set_df_property("undeposited_entries", "cannot_add_rows", true);
		frm.set_df_property("undeposited_entries", "cannot_delete_rows", true);
		frm.set_df_property("undeposited_entries", "disable_sorting", true);

		$(frm.wrapper).on("grid-row-render", function (e, grid_row) {
			frm.events.toggle_highlight(grid_row);
		});

		frm.events.process_route_options(frm);
	},

	process_route_options(frm) {
		if (!frappe.route_options || $.isEmptyObject(frappe.route_options)) {
			return;
		}

		let route_fields = frm.events.get_route_fields(frm);
		for (let f of route_fields) {
			if (frappe.route_options[f] != null) {
				frm.doc[f] = frappe.route_options[f];
			}
		}

		if (frappe.route_options.undeposited_account) {
			frm.doc.undeposited_account = frappe.route_options.undeposited_account;
		}
		if (frappe.route_options.bank_account) {
			frm.doc.bank_account = frappe.route_options.bank_account;
		}
		if (frappe.route_options.deposit_date) {
			frm.doc.deposit_date = frappe.route_options.deposit_date;
		}

		if (frm.doc.undeposited_account && frm.doc.deposit_date) {
			frm.events.get_undeposited_entries(frm);
		}
	},

	set_query_params(frm) {
		let full_url = window.location.href.replace(window.location.search, "");

		let route_fields = frm.events.get_route_fields(frm);
		let route_obj = Object.fromEntries(route_fields.map(f => [f, frm.doc[f]]));

		let query_params = Object.entries(route_obj)
			.map(([field, value]) => `${field}=${encodeURIComponent(cstr(value))}`)
			.filter(Boolean)
			.join("&");

		if (query_params) {
			full_url += "?" + query_params;
		}
		window.history.replaceState(null, null, full_url);
	},

	get_route_fields(frm) {
		let route_fields = [
			'undeposited_account',
			'bank_account',
			'deposit_date',
		];

		let meta = frappe.get_meta(frm.doc.doctype);
		let mandatory_fields = meta.fields.filter((df) => {
			return (
				df.reqd
				&& !df.read_only
				&& !frappe.model.table_fields.includes(df.fieldtype)
				&& !frappe.model.no_value_type.includes(df.fieldtype)
				&& !route_fields.includes(df.fieldname)
				&& df.fieldname != 'deposit_no'
			);
		});

		route_fields = route_fields.concat(mandatory_fields.map(df => df.fieldname));
		return route_fields;
	},

	refresh(frm) {
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

		frm.events.get_other_company_accounts_and_cost_centers(frm);
	},

	onload(frm) {
		frm.fields_dict.totals_section.wrapper.addClass("banking-sticky-section");
	},

	onload_post_render: function (frm) {
		frm.events.setup_row_checkbox_selection(frm);
	},

	setup_queries(frm) {
		frm.set_query("bank_account", function() {
			return {
				filters: {
					"company": frm.doc.company,
					"is_company_account": 1,
				}
			};
		});

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

	setup_amount_formatters(frm) {
		let selected_deposit_df = frappe.meta.get_docfield("Bank Deposit Tool", "selected_deposit_amount");
		let difference_df = frappe.meta.get_docfield("Bank Deposit Tool", "difference_amount");
		let total_adjustment_df = frappe.meta.get_docfield("Bank Deposit Tool", "total_adjustment");

		selected_deposit_df.formatter = (value, df, options, doc) => {
			return erpnext.utils.banking_amount_formatter(value, df, options, doc);
		}
		difference_df.formatter = (value, df, options, doc) => {
			return erpnext.utils.banking_amount_formatter(value, df, options, doc, "var(--red-700)", "var(--green-800)");
		}
		total_adjustment_df.formatter = (value, df, options, doc) => {
			return erpnext.utils.banking_amount_formatter(value, df, options, doc, "var(--red-700)");
		}
	},

	setup_row_checkbox_selection(frm) {
		// reconcile when the row is selected or deselected
		frm.fields_dict.undeposited_entries.grid.wrapper.on('click', '.grid-row-check', (e) => {
			frm.doc.actual_deposit_amount = frm.events.get_selected_deposit_amount(frm);
			frm.events.calculate_totals(frm);

			const $check = $(e.currentTarget);
			const is_select_all = $check.parents(".grid-heading-row:first").length !== 0;
			const docname = $check.parents(".grid-row:first")?.attr("data-name");
			const grid_row = docname ? frm.fields_dict.undeposited_entries.grid.get_row(docname) : null;
			if (is_select_all) {
				for (let d of frm.fields_dict.undeposited_entries.grid.grid_rows) {
					frm.events.toggle_highlight(d);
				}
			} else if (grid_row) {
				frm.events.toggle_highlight(grid_row);
			}
		});
	},

	company(frm) {
		frm.events.get_other_company_accounts_and_cost_centers(frm);
	},

	bank_account(frm) {
		frm.events.get_bank_account_details(frm);
		frm.events.set_query_params(frm);
	},

	undeposited_account(frm) {
		frm.events.get_undeposited_entries(frm);
	},

	deposit_date(frm) {
		frm.events.get_undeposited_entries(frm);
	},

	from_date(frm) {
		frm.events.get_undeposited_entries(frm);
	},

	to_date(frm) {
		frm.events.get_undeposited_entries(frm);
	},

	min_amount(frm) {
		frm.events.get_undeposited_entries(frm);
	},

	max_amount(frm) {
		frm.events.get_undeposited_entries(frm);
	},

	mode_of_payment(frm) {
		frm.events.get_undeposited_entries(frm);
	},

	actual_deposit_amount(frm) {
		frm.events.calculate_totals(frm);
	},

	calculate_totals(frm) {
		frm.doc.selected_deposit_amount = frm.events.get_selected_deposit_amount(frm);
		frm.doc.actual_deposit_amount = flt(frm.doc.actual_deposit_amount, precision("actual_deposit_amount"));

		frm.doc.total_adjustment = 0;
		for (let d of frm.doc.adjustment_entries || []) {
			d.adjustment_amount = flt(d.adjustment_amount, precision("adjustment_amount", d));
			frm.doc.total_adjustment += d.adjustment_amount;
		}

		frm.doc.difference_amount = (
			frm.doc.selected_deposit_amount
			- frm.doc.actual_deposit_amount
			- frm.doc.total_adjustment
		);

		frm.refresh_field("selected_deposit_amount");
		frm.refresh_field("actual_deposit_amount");
		frm.refresh_field("total_adjustment");
		frm.refresh_field("difference_amount");
	},

	get_selected_deposit_amount(frm) {
		let selected_rows = frm.fields_dict.undeposited_entries.grid.get_selected_children();

		let selected_deposit_amount = 0;
		for (let d of selected_rows || []) {
			selected_deposit_amount += flt(d.amount);
		}

		return selected_deposit_amount;
	},

	get_bank_account_details(frm) {
		if (frm.events.bank_account) {
			return frappe.call({
				method: "erpnext.accounts.doctype.bank_account.bank_account.get_bank_account_details",
				args: {
					bank_account: frm.doc.bank_account
				},
				callback: (r) => {
					if (r.message) {
						frm.set_value("deposit_to_account", r.message.suspense_account || r.message.account);
					}
				}
			});
		}
	},

	reload_undeposited_entries(frm) {
		if (!frm.doc.undeposited_account || !frm.doc.deposit_date) {
			frappe.msgprint(__("Please select Undeposited Funds Account and Deposit Date"));
			return;
		}
		frm.events.get_undeposited_entries(frm);
	},

	get_undeposited_entries(frm) {
		if (!frm.doc.undeposited_account || !frm.doc.deposit_date) {
			return;
		}

		let selected_vouchers = frm.events.get_selected_vouchers(frm);

		return frm.call({
			doc: frm.doc,
			method: 'get_undeposited_entries',
			freeze: true,
			freeze_message: __("Loading Undeposited Entries"),
			callback: () => {
				frm.events.set_selected_vouchers(frm, selected_vouchers);
				frm.events.calculate_totals(frm);
				frm.events.set_query_params(frm);
			}
		});
	},

	submit_deposit_entry(frm) {
		let selected_row_names = frm.events.get_selected_rows(frm).map(d => d.name);
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

	make_deposit_entry(frm) {
		let selected_row_names = frm.events.get_selected_rows(frm).map(d => d.name);
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

	set_selected_vouchers(frm, selected_vouchers) {
		for (let row of frm.doc.undeposited_entries || []) {
			let v = [
				row.voucher_type,
				row.voucher_no,
				row.voucher_detail_dt || null,
				row.voucher_detail_dn || null,
			];

			if (selected_vouchers.some(d => d[0] == v[0] && d[1] == v[1] && d[2] == v[2] && d[3] == v[3])) {
				row.__checked = 1;
			} else {
				row.__checked = 0;
			}
		}

		frm.refresh_field("undeposited_entries");
	},

	get_selected_vouchers(frm) {
		let selected_rows = frm.events.get_selected_rows(frm);
		return selected_rows.map(d => [
			d.voucher_type,
			d.voucher_no,
			d.voucher_detail_dt || null,
			d.voucher_detail_dn || null,
		]);
	},

	get_selected_rows(frm) {
		return frm.fields_dict.undeposited_entries?.grid?.get_selected_children() || [];
	},

	get_other_company_accounts_and_cost_centers(frm) {
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

	toggle_highlight(grid_row) {
		if (!grid_row || !grid_row.doc || grid_row.doc.doctype != "Bank Deposit Undeposited Entry") {
			return;
		}
		grid_row.row.toggleClass("highlight", Boolean(grid_row.doc.__checked));
	},
});

frappe.ui.form.on("Bank Deposit Adjustment", {
	supplier(frm, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		if (row.supplier && frm.doc.company) {
			return frappe.call({
				method: "erpnext.accounts.party.get_party_account",
				args: {
					company: frm.doc.company,
					party_type: "Supplier",
					party: row.supplier,
				},
				callback: (r) => {
					if (r.message) {
						frappe.model.set_value(row.doctype, row.name, "account", r.message);
					}
				}
			});
		}
	},

	adjustment_amount(frm) {
		frm.events.calculate_totals(frm);
	},
	adjustment_entries_remove(frm) {
		frm.events.calculate_totals(frm);
	},
});
