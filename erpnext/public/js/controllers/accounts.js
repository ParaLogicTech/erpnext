// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

// get tax rate
frappe.provide("erpnext.taxes");
frappe.provide("erpnext.taxes.flags");

frappe.ui.form.on(cur_frm.doctype, {
	setup: function(frm) {
		// set conditional display for rate column in taxes
		// $(frm.wrapper).on('grid-row-render', function(e, grid_row) {
		// 	if(in_list(['Sales Taxes and Charges', 'Purchase Taxes and Charges'], grid_row.doc.doctype)) {
		// 		erpnext.taxes.set_conditional_mandatory_rate_or_amount(grid_row);
		// 	}
		// });
	},
	onload: function(frm) {
		if(frm.get_field("taxes")) {
			frm.set_query("account_head", "taxes", function(doc) {
				if(frm.cscript.tax_table == "Sales Taxes and Charges") {
					var account_type = ["Tax", "Chargeable", "Expense Account"];
				} else {
					var account_type = ["Tax", "Chargeable", "Income Account", "Expenses Included In Valuation"];
				}

				return {
					query: "erpnext.controllers.queries.tax_account_query",
					filters: {
						"account_type": account_type,
						"company": doc.company
					}
				}
			});

			frm.set_query("cost_center", "taxes", function(doc) {
				return {
					filters: {
						'company': doc.company,
						"is_group": 0
					}
				}
			});
		}
	},
	refresh: function (frm) {
		if (frm.doc.docstatus === 0 && frm.fields_dict.taxes) {
			frm.fields_dict.taxes.grid.add_custom_button(__("Set Manual Distribution"), function() {
				if (frm.focused_tax_dn) {
					frm.cscript.set_manual_distribution(frm.doc, frm.cscript.tax_table, frm.focused_tax_dn);
				}
			});
			frm.fields_dict.taxes.grid.custom_buttons[__("Set Manual Distribution")].addClass('hidden');
		}

		if (frm.fields_dict.taxes) {
			frm.fields_dict.taxes.grid.grid_rows.forEach(grid_row => erpnext.taxes.set_conditional_mandatory_rate_or_amount(grid_row));
		}
	},
	validate: function(frm) {
		// neither is absolutely mandatory
		if(frm.get_docfield("taxes")) {
			frm.get_docfield("taxes", "rate").reqd = 0;
			frm.get_docfield("taxes", "tax_amount").reqd = 0;
		}

	},
	taxes_on_form_rendered: function(frm) {
		erpnext.taxes.set_conditional_mandatory_rate_or_amount(frm.open_grid_row());
	},

	allocate_advances_automatically: function(frm) {
		if(frm.doc.allocate_advances_automatically) {
			frappe.call({
				doc: frm.doc,
				method: "set_advances",
				callback: function(r, rt) {
					refresh_field("advances");
					frm.cscript.calculate_taxes_and_totals && frm.cscript.calculate_taxes_and_totals();
				}
			})
		}
	}
});

frappe.ui.form.on('Sales Invoice Payment', {
	mode_of_payment: function(frm, cdt, cdn) {
		var d = locals[cdt][cdn];
		get_payment_mode_account(frm, d.mode_of_payment, function(account){
			frappe.model.set_value(cdt, cdn, 'account', account)
		})
	}
});

frappe.ui.form.on("Sales Invoice", {
	payment_terms_template: function() {
		cur_frm.trigger("disable_due_date");
	}
});

frappe.ui.form.on('Purchase Invoice', {
	mode_of_payment: function(frm) {
		get_payment_mode_account(frm, frm.doc.mode_of_payment, function(account){
			frm.set_value('cash_bank_account', account);
		})
	},

	payment_terms_template: function() {
		cur_frm.trigger("disable_due_date");
	}
});

frappe.ui.form.on("Payment Schedule", {
	payment_schedule_remove: function() {
		cur_frm.trigger("disable_due_date");
	},

});

frappe.ui.form.on('Payment Entry', {
	mode_of_payment: function(frm) {
		get_payment_mode_account(frm, frm.doc.mode_of_payment, function(account){
			var payment_account_field = frm.doc.payment_type == "Receive" ? "paid_to" : "paid_from";
			frm.set_value(payment_account_field, account);
		})
	}
})

frappe.ui.form.on('Salary Structure', {
	mode_of_payment: function(frm) {
		get_payment_mode_account(frm, frm.doc.mode_of_payment, function(account){
			frm.set_value("payment_account", account);
		})
	}
})

var get_payment_mode_account = function(frm, mode_of_payment, callback) {
	if(!frm.doc.company) {
		frappe.throw({message:__("Please select a Company first."), title: __("Mandatory")});
	}

	if(!mode_of_payment) {
		return;
	}

	return  frappe.call({
		method: "erpnext.accounts.doctype.sales_invoice.sales_invoice.get_bank_cash_account",
		args: {
			"mode_of_payment": mode_of_payment,
			"company": frm.doc.company
		},
		callback: function(r, rt) {
			if(r.message) {
				callback(r.message.account)
			}
		}
	});
}

cur_frm.cscript.account_head = function(doc, cdt, cdn) {
	let d = locals[cdt][cdn];
	if (!d.charge_type && d.account_head) {
		frappe.msgprint(__("Please select Charge Type first"));
		frappe.model.set_value(cdt, cdn, "account_head", "");
	} else if (d.account_head) {
		return frappe.call({
			type: "GET",
			method: "erpnext.accounts.doctype.account.account.get_tax_account_details",
			args: {
				account_head: d.account_head
			},
			callback: function(r) {
				if (r.message) {
					frappe.model.set_value(cdt, cdn, "description", r.message.account_name);
					frappe.model.set_value(cdt, cdn, "exclude_from_item_tax_amount", cint(r.message.exclude_from_item_tax_amount));

					if (["Actual", "Manual"].includes(d.charge_type)) {
						frappe.model.set_value(cdt, cdn, "rate", flt(r.message.tax_rate) || 0);
					} else {
						frappe.model.set_value(cdt, cdn, "rate", 0);
					}
				}
			}
		});
	}
}

cur_frm.cscript.validate_taxes_and_charges = function(cdt, cdn) {
	var d = locals[cdt][cdn];
	var msg = "";

	if(d.account_head && !d.description) {
		// set description from account head
		d.description = d.account_head.split(' - ').slice(0, -1).join(' - ');
	}

	if(!d.charge_type && (d.row_id || d.rate || d.tax_amount)) {
		msg = __("Please select Charge Type first");
		d.row_id = "";
		d.rate = d.tax_amount = 0.0;
	} else if((d.charge_type !== 'On Previous Row Amount' && d.charge_type !== 'On Previous Row Total') && d.row_id) {
		msg = __("Can refer row only if the charge type is 'On Previous Row Amount' or 'Previous Row Total'");
		d.row_id = "";
	} else if((d.charge_type == 'On Previous Row Amount' || d.charge_type == 'On Previous Row Total') && d.row_id) {
		if (d.idx == 1) {
			msg = __("Cannot select charge type as 'On Previous Row Amount' or 'On Previous Row Total' for first row");
			d.charge_type = '';
		} else if (!d.row_id) {
			msg = __("Please specify a valid Row ID for row {0} in table {1}", [d.idx, __(d.doctype)]);
			d.row_id = "";
		} else if(d.row_id && d.row_id >= d.idx) {
			msg = __("Cannot refer row number greater than or equal to current row number for this Charge type");
			d.row_id = "";
		}
	}
	if(msg) {
		frappe.validated = false;
		refresh_field("taxes");
		frappe.throw(msg);
	}

}

cur_frm.cscript.validate_inclusive_tax = function(tax) {
	var actual_type_error = function() {
		var msg = __("Actual/Weighted Distribution/Manual type tax cannot be included in Item rate in row {0}", [tax.idx])
		frappe.throw(msg);
	};

	var on_previous_row_error = function(row_range) {
		var msg = __("For row {0} in {1}. To include {2} in Item rate, rows {3} must also be included",
			[tax.idx, __(tax.doctype), tax.charge_type, row_range])
		frappe.throw(msg);
	};

	if(cint(tax.included_in_print_rate)) {
		if(tax.charge_type === "Actual" || tax.charge_type === "Weighted Distribution" || tax.charge_type === "Manual") {
			// inclusive tax cannot be of type Actual
			actual_type_error();
		} else if(tax.charge_type == "On Previous Row Amount" &&
			!cint(this.frm.doc["taxes"][tax.row_id - 1].included_in_print_rate)
		) {
			// referred row should also be an inclusive tax
			on_previous_row_error(tax.row_id);
		} else if(tax.charge_type == "On Previous Row Total") {
			var taxes_not_included = $.map(this.frm.doc["taxes"].slice(0, tax.row_id),
				function(t) { return cint(t.included_in_print_rate) ? null : t; });
			if(taxes_not_included.length > 0) {
				// all rows above this tax should be inclusive
				on_previous_row_error(tax.row_id == 1 ? "1" : "1 - " + tax.row_id);
			}
		} else if(tax.category == "Valuation") {
			frappe.throw(__("Valuation type charges can not marked as Inclusive"));
		}
	}
}

cur_frm.cscript.set_manual_distribution = function(doc, cdt, cdn) {
	var me = this;
	var tax_row = frappe.get_doc(cdt, cdn);
	if (!tax_row) {
		return;
	}

	var company_currency = this.get_company_currency();

	var itemised_rows = [];
	$.each(me.frm.doc.items || [], function(i, item_row) {
		var item_key = item_row.item_code || item_row.item_name;
		var tax_amount = flt(JSON.parse(tax_row.manual_distribution_detail || '{}')[item_key]);

		var current_row = itemised_rows.filter(d => (d.item_code || d.item_name) === item_key);
		if (current_row && current_row.length) {
			current_row = current_row[0];
		} else {
			current_row = {
				item_code: item_row.item_code,
				item_name: item_row.item_name,
				net_amount: 0,
				tax_amount: tax_amount,
				currency: me.frm.doc.calculate_tax_on_company_currency ? company_currency : me.frm.doc.currency
			};
			itemised_rows.push(current_row);
		}

		current_row.net_amount += me.frm.doc.calculate_tax_on_company_currency ? item_row.base_net_amount : item_row.net_amount;
	});

	let table_data = [];

	var dialog = new frappe.ui.Dialog({
		title: __("Manual Distribution for {0}", [tax_row.description]),
		size: "extra-large",
		fields: [
			{label: __("Items"), fieldname: "items", fieldtype: "Table", data: table_data,
				get_data: () => table_data,
				cannot_add_rows: true, in_place_edit: true,
				fields: [
					{
						label: __('Item Code'),
						fieldname:"item_code",
						fieldtype:'Link',
						options: 'Item',
						read_only: 1,
						in_list_view: 1,
						columns: 6,
					},
					{
						label: __('Item Name'),
						fieldname:"item_name",
						fieldtype:'Data',
						read_only: 1,
						in_list_view: 0,
						columns: 4,
					},
					{
						label: __('Net Amount'),
						fieldtype:'Currency',
						options: 'currency',
						fieldname:"net_amount",
						read_only: 1,
						in_list_view: 1,
						columns: 2,
					},
					{
						label: __(tax_row.description),
						fieldtype:'Currency',
						options: 'currency',
						fieldname:"tax_amount",
						in_list_view: 1,
						columns: 2,
					}
				]
			}
		]
	});

	dialog.fields_dict.items.df.data = itemised_rows;
	table_data = dialog.fields_dict.items.df.data;
	dialog.fields_dict.items.grid.refresh();

	dialog.show();
	dialog.set_primary_action(__('Update'), function() {
		var updated_items = this.get_values()["items"];
		$.each(updated_items || [], function(i, d) {
			var item_key = d.item_code || d.item_name;
			var distribution_detail = JSON.parse(tax_row.manual_distribution_detail || '{}');
			distribution_detail[item_key] = flt(d.tax_amount);
			tax_row.manual_distribution_detail = JSON.stringify(distribution_detail);
		});

		me.frm.dirty();
		me.calculate_taxes_and_totals();
		dialog.hide();
	});
}

if(!erpnext.taxes.flags[cur_frm.cscript.tax_table]) {
	erpnext.taxes.flags[cur_frm.cscript.tax_table] = true;

	frappe.ui.form.on(cur_frm.cscript.tax_table, "row_id", function(frm, cdt, cdn) {
		cur_frm.cscript.validate_taxes_and_charges(cdt, cdn);
	});

	frappe.ui.form.on(cur_frm.cscript.tax_table, "rate", function(frm, cdt, cdn) {
		cur_frm.cscript.validate_taxes_and_charges(cdt, cdn);
	});

	frappe.ui.form.on(cur_frm.cscript.tax_table, "tax_amount", function(frm, cdt, cdn) {
		cur_frm.cscript.validate_taxes_and_charges(cdt, cdn);
	});

	frappe.ui.form.on(cur_frm.cscript.tax_table, "charge_type", function(frm, cdt, cdn) {
		frm.cscript.validate_taxes_and_charges(cdt, cdn);
		var open_form = frm.open_grid_row();
		if(open_form) {
			erpnext.taxes.set_conditional_mandatory_rate_or_amount(open_form);
		} else {
			// apply in current row
			erpnext.taxes.set_conditional_mandatory_rate_or_amount(frm.get_field('taxes').grid.get_row(cdn));
		}

		frm.cscript.calculate_taxes_and_totals();
		var row = frappe.get_doc(cdt, cdn);
		if (row.charge_type === "Manual") {
			frm.cscript.set_manual_distribution(frm.doc, cdt, cdn);
		}
	});

	frappe.ui.form.on(cur_frm.cscript.tax_table, "taxes_before_row_focused", function(frm, cdt, cdn) {
		var row = frappe.get_doc(cdt, cdn);
		frm.focused_tax_dn = cdn;
		frm.fields_dict.taxes.grid.custom_buttons[__("Set Manual Distribution")].toggleClass('hidden', row.charge_type !== 'Manual');
		erpnext.taxes.set_conditional_mandatory_rate_or_amount(frm.get_field('taxes').grid.get_row(cdn));
	});

	frappe.ui.form.on(cur_frm.cscript.tax_table, "included_in_print_rate", function(frm, cdt, cdn) {
		var tax = frappe.get_doc(cdt, cdn);
		try {
			cur_frm.cscript.validate_taxes_and_charges(cdt, cdn);
			cur_frm.cscript.validate_inclusive_tax(tax);
		} catch(e) {
			tax.included_in_print_rate = 0;
			refresh_field("included_in_print_rate", tax.name, tax.parentfield);
			throw e;
		}
	});
}

erpnext.taxes.set_conditional_mandatory_rate_or_amount = function(grid_row) {
	if(grid_row) {
		let doc = grid_row.doc
		let amount_editable = doc.charge_type === "Actual" || doc.charge_type === "Weighted Distribution";
		let rate_editable = doc.charge_type !== "Actual" && doc.charge_type !== "Manual"

		grid_row.toggle_editable("tax_amount", amount_editable, true);
		grid_row.toggle_editable("base_tax_amount", amount_editable, true);
		grid_row.toggle_reqd("tax_amount", amount_editable, true);

		grid_row.toggle_editable("rate", rate_editable, true);
		grid_row.toggle_reqd("rate", rate_editable, true);
	}
}
