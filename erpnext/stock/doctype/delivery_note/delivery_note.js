// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

{% include 'erpnext/selling/sales_common.js' %};

frappe.provide("erpnext.stock");
frappe.provide("erpnext.stock.delivery_note");

frappe.ui.form.on("Delivery Note", {
	setup: function(frm) {
		frm.custom_make_buttons = {
			'Packing Slip': 'Packing Slip',
			'Installation Note': 'Installation Note',
			'Sales Invoice': 'Sales Invoice',
			'Delivery Note': 'Delivery Return',
			'Auto Repeat': 'Subscription',
			'Delivery Trip': 'Delivery Trip',
		};

		erpnext.queries.setup_queries(frm, "Warehouse", function() {
			return erpnext.queries.warehouse(frm.doc);
		});
		erpnext.queries.setup_warehouse_qty_query(frm);

		frm.set_query('transporter', function() {
			return {
				filters: {
					'is_transporter': 1
				}
			}
		});

		frm.set_query('driver', function(doc) {
			return {
				filters: {
					'transporter': doc.transporter
				}
			}
		});


		frm.set_query('expense_account', 'items', function(doc, cdt, cdn) {
			if (erpnext.is_perpetual_inventory_enabled(doc.company)) {
				return {
					filters: {
						"report_type": "Profit and Loss",
						"company": doc.company,
						"is_group": 0
					}
				}
			}
		});

		frm.set_query('cost_center', 'items', function(doc, cdt, cdn) {
			if (erpnext.is_perpetual_inventory_enabled(doc.company)) {
				return {
					filters: {
						'company': doc.company,
						"is_group": 0
					}
				}
			}
		});


	},

	print_without_amount: function(frm) {
		erpnext.stock.delivery_note.set_print_hide(frm.doc);
	},

	refresh: function(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.is_return && frm.doc.billing_status == "To Bill" && frappe.model.can_create("Sales Invoice")) {
			frm.add_custom_button(__('Credit Note'), function() {
				frappe.model.open_mapped_doc({
					method: "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_invoice",
					frm: cur_frm,
				})
			}, __('Create'));
		}
	}
});

frappe.ui.form.on("Delivery Note Item", {
	expense_account: function(frm, dt, dn) {
		var d = locals[dt][dn];
		frm.update_in_all_rows('items', 'expense_account', d.expense_account);
	},
	cost_center: function(frm, dt, dn) {
		var d = locals[dt][dn];
		frm.update_in_all_rows('items', 'cost_center', d.cost_center);
	}
});

erpnext.stock.DeliveryNoteController = class DeliveryNoteController extends erpnext.selling.SellingController {
	setup(doc) {
		this.setup_posting_date_time_check();
		super.setup(doc);
		this.frm.make_methods = {
			'Delivery Trip': this.make_delivery_trip,
		};
	}
	refresh(doc, dt, dn) {
		var me = this;
		super.refresh();

		if (me.frm.doc.docstatus == 0) {
			me.add_get_latest_price_button();
			if (erpnext.utils.has_valuation_read_permission()) {
				me.add_set_rate_as_cost_button();
			}
		}
		if (me.frm.doc.docstatus == 1) {
			me.add_update_price_list_button();
		}

		if ((!doc.is_return) && (doc.status!="Closed" || this.frm.is_new())) {
			if (this.frm.doc.docstatus === 0) {
				if (frappe.model.can_read("Sales Order")) {
					this.frm.add_custom_button(__('Sales Order'), function () {
						me.get_items_from_sales_order();
					}, __("Get Items From"));
				}

				if (frappe.model.can_read("Packing Slip")) {
					this.frm.add_custom_button(__('Packing Slip'), function () {
						me.get_items_from_packing_slip("Delivery Note");
					}, __("Get Items From"));
				}

				me.add_get_applicable_items_button("stock");
				me.add_get_project_template_items_button("stock");
			}
		}

		if (doc.docstatus==1) {
			this.show_stock_ledger();
			if (erpnext.is_perpetual_inventory_enabled(doc.company)) {
				this.show_general_ledger();
			}
			if (this.frm.has_perm("submit") && doc.status !== "Closed") {
				me.frm.add_custom_button(__("Close"), function() { me.close_delivery_note() },
					__("Status"));
			}
		}

		if(doc.docstatus==1 && doc.status === "Closed" && this.frm.has_perm("submit")) {
			this.frm.add_custom_button(__('Re-Open'), function() { me.reopen_delivery_note() },
				__("Status"));
		}
		erpnext.stock.delivery_note.set_print_hide(doc, dt, dn);

		if(doc.docstatus == 1 && !doc.is_return && doc.status != "Closed" && flt(doc.per_completed) < 100) {
			// show Make Invoice button only if Delivery Note is not created from Sales Invoice
			var from_sales_invoice = false;
			from_sales_invoice = me.frm.doc.items.some(function(item) {
				return item.sales_invoice ? true : false;
			});

			if (!from_sales_invoice && frappe.model.can_create("Sales Invoice")) {
				this.frm.add_custom_button(__('Sales Invoice'), function() { me.make_sales_invoice() },
					__('Create'));
			}
		}

		if (!doc.is_return && doc.status!="Closed") {
			if (doc.docstatus == 1 && frappe.model.can_create("Delivery Note")) {
				this.frm.add_custom_button(__('Delivery Return'), function() {
					me.make_sales_return() }, __('Create'));
			}

			if(flt(doc.per_installed, 2) < 100 && doc.docstatus==1 && frappe.model.can_create("Installation Note")) {
				this.frm.add_custom_button(__('Installation Note'), function () {
					me.make_installation_note()
				}, __('Create'));
			}

			if (doc.docstatus==1 && frappe.model.can_create("Delivery Trip")) {
				this.frm.add_custom_button(__('Delivery Trip'), function() {
					me.make_delivery_trip() }, __('Create'));
			}

			if (!doc.__islocal && doc.docstatus==1) {
				this.frm.page.set_inner_btn_group_as_primary(__('Create'));
			}

			if (doc.docstatus === 0) {
				this.frm.fields_dict.items.grid.add_custom_button(__("Update Qty from Availability"), function() {
					me.update_item_qty_from_availability()
				});
			}

			if (me.frm.doc.docstatus === 1 && !me.frm.doc.inter_company_reference) {
				if (me.frm.doc.__onload?.is_internal_customer) {
					me.frm.add_custom_button("Inter Company Receipt", function() {
						me.make_inter_company_receipt();
					}, __('Create'));
				}
			}
		}

		if(doc.docstatus == 1 && !doc.is_return && !doc.auto_repeat && frappe.model.can_create("Auto Repeat")) {
			me.frm.add_custom_button(__('Subscription'), function() {
				erpnext.utils.make_subscription(doc.doctype, doc.name)
			}, __('Create'))
		}

		this.frm.set_indicator_formatter('item_code', function(doc) {
			if (doc.docstatus === 0) {
				if (!doc.is_stock_item) {
					return "blue";
				} else if (!doc.actual_qty) {
					return "red";
				} else if (doc.actual_qty < doc.stock_qty) {
					return "orange";
				} else {
					return "green";
				}
			} else if (doc.docstatus === 1) {
				let completed_qty = flt(doc.billed_qty) + flt(doc.returned_qty);
				if (doc.returned_qty && doc.returned_qty >= doc.qty) {
					return "grey";
				} else if (doc.skip_sales_invoice) {
					return "blue"
				} else if (!completed_qty) {
					return "orange";
				} else if (completed_qty < doc.qty) {
					return "yellow";
				} else if (doc.billed_qty < doc.qty) {
					return "blue";
				} else {
					return "green";
				}
			}
		});
	}

	get_items_from_sales_order() {
		erpnext.utils.map_current_doc({
			method: "erpnext.selling.doctype.sales_order.sales_order.make_delivery_note",
			source_doctype: "Sales Order",
			target: this.frm,
			setters: [
				{
					fieldtype: 'Link',
					label: __('Customer'),
					options: 'Customer',
					fieldname: 'customer',
					default: this.frm.doc.customer || undefined,
				},
				{
					fieldtype: 'Link',
					label: __('Project'),
					options: 'Project',
					fieldname: 'project',
					default: this.frm.doc.project || undefined,
				},
				{
					fieldtype: 'DateRange',
					label: __('Date Range'),
					fieldname: 'transaction_date',
				}
			],
			columns: ['customer_name', 'transaction_date', 'project'],
			get_query_filters: {
				docstatus: 1,
				status: ["not in", ["Closed", "On Hold"]],
				delivery_status: "To Deliver",
				skip_delivery_note: 0,
				company: this.frm.doc.company,
				customer: this.frm.doc.customer || undefined,
			}
		});
	}

	make_sales_invoice() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_invoice",
			frm: this.frm
		})
	}

	make_inter_company_receipt() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.delivery_note.delivery_note.make_inter_company_purchase_receipt",
			frm: this.frm
		});
	}

	make_installation_note() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.delivery_note.delivery_note.make_installation_note",
			frm: this.frm
		});
	}

	make_sales_return() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_return",
			frm: this.frm
		})
	}

	make_delivery_trip() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.delivery_note.delivery_note.make_delivery_trip",
			frm: this.frm
		})
	}

	update_item_qty_from_availability() {
		var me = this;
		var items = [];
		$.each(me.frm.doc.items || [], function(i, d) {
			items.push({
				name: d.name,
				item_code: d.item_code,
				warehouse: d.warehouse,
				stock_qty: d.stock_qty,
				conversion_factor: d.conversion_factor
			});
		});

		if(items.length) {
			frappe.call({
				method: "erpnext.controllers.stock_controller.update_item_qty_from_availability",
				args: {
					"items": items
				},
				freeze: true,
				callback: function(r) {
					if(!r.exc) {
						$.each(r.message || {}, function(cdn, row) {
							$.each(row || {}, function(fieldname, value) {
								frappe.model.set_value("Delivery Note Item", cdn, fieldname, value);
							});
						});
					}
				}
			});
		}
	}

	tc_name() {
		this.get_terms();
	}

	items_on_form_rendered() {
		erpnext.setup_serial_no();
	}

	packed_items_on_form_rendered() {
		erpnext.setup_serial_no();
	}

	close_delivery_note(doc) {
		this.update_status("Closed")
	}

	reopen_delivery_note () {
		this.update_status("Submitted")
	}

	update_status(status) {
		var me = this;
		frappe.ui.form.is_saving = true;
		frappe.call({
			method:"erpnext.stock.doctype.delivery_note.delivery_note.update_delivery_note_status",
			args: {docname: me.frm.doc.name, status: status},
			callback: function(r){
				if(!r.exc)
					me.frm.reload_doc();
			},
			always: function(){
				frappe.ui.form.is_saving = false;
			}
		})
	}

	to_warehouse() {
		let packed_items_table = this.frm.doc["packed_items"];
		erpnext.utils.autofill_warehouse(this.frm.doc["items"], "target_warehouse", this.frm.doc.to_warehouse, 1);
		if (packed_items_table && packed_items_table.length) {
			erpnext.utils.autofill_warehouse(packed_items_table, "target_warehouse", this.frm.doc.to_warehouse, 1);
		}
	}

};

extend_cscript(cur_frm.cscript, new erpnext.stock.DeliveryNoteController({frm: cur_frm}));

frappe.ui.form.on('Delivery Note', {
	setup: function(frm) {
		if(frm.doc.company) {
			frm.trigger("unhide_account_head");
		}
	},

	company: function(frm) {
		frm.trigger("unhide_account_head");
	},

	unhide_account_head: function(frm) {
		// unhide expense_account and cost_center if perpetual inventory is enabled in the company
		var aii_enabled = erpnext.is_perpetual_inventory_enabled(frm.doc.company)
		frm.fields_dict["items"].grid.set_column_disp(["expense_account", "cost_center"], aii_enabled);
	}
})


erpnext.stock.delivery_note.set_print_hide = function(doc, cdt, cdn){
	var dn_fields = frappe.meta.docfield_map['Delivery Note'];
	var dn_item_fields = frappe.meta.docfield_map['Delivery Note Item'];
	var dn_fields_copy = dn_fields;
	var dn_item_fields_copy = dn_item_fields;
	if (doc.print_without_amount) {
		dn_fields['currency'].print_hide = 1;
		dn_item_fields['rate'].print_hide = 1;
		dn_item_fields['discount_percentage'].print_hide = 1;
		dn_item_fields['price_list_rate'].print_hide = 1;
		dn_item_fields['amount'].print_hide = 1;
		dn_item_fields['discount_amount'].print_hide = 1;
		dn_fields['taxes'].print_hide = 1;
	} else {
		if (dn_fields_copy['currency'].print_hide != 1)
			dn_fields['currency'].print_hide = 0;
		if (dn_item_fields_copy['rate'].print_hide != 1)
			dn_item_fields['rate'].print_hide = 0;
		if (dn_item_fields_copy['amount'].print_hide != 1)
			dn_item_fields['amount'].print_hide = 0;
		if (dn_item_fields_copy['discount_amount'].print_hide != 1)
			dn_item_fields['discount_amount'].print_hide = 0;
		if (dn_fields_copy['taxes'].print_hide != 1)
			dn_fields['taxes'].print_hide = 0;
	}
}
