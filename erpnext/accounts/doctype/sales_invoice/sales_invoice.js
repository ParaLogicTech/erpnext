// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

{% include 'erpnext/selling/sales_common.js' %};

frappe.provide("erpnext.accounts");

erpnext.accounts.SalesInvoiceController = class SalesInvoiceController extends erpnext.selling.SellingController {
	setup(doc) {
		this.setup_posting_date_time_check();
		super.setup(doc);
	}

	onload() {
		var me = this;
		super.onload();

		if(!this.frm.doc.__islocal && !this.frm.doc.customer && this.frm.doc.debit_to) {
			// show debit_to in print format
			this.frm.set_df_property("debit_to", "print_hide", 0);
		}

		erpnext.queries.setup_queries(this.frm, "Warehouse", function() {
			return erpnext.queries.warehouse(me.frm.doc);
		});
		erpnext.queries.setup_warehouse_qty_query(this.frm);

		if(this.frm.doc.__islocal && this.frm.doc.is_pos) {
			//Load pos profile data on the invoice if the default value of Is POS is 1

			me.frm.script_manager.trigger("is_pos");
			me.frm.refresh_fields();
		}
	}

	refresh(doc, dt, dn) {
		const me = this;
		super.refresh();
		if(cur_frm.msgbox && cur_frm.msgbox.$wrapper.is(":visible")) {
			// hide new msgbox
			cur_frm.msgbox.hide();
		}

		this.frm.toggle_reqd("due_date", !this.frm.doc.is_return);

		if (this.frm.doc.is_return) {
			this.frm.return_print_format = "Sales Invoice Return";
		}

		if (doc.docstatus == 1 && cint(doc.is_fbr_pos_invoice) && !doc.fbr_pos_invoice_no && this.frm.has_perm("submit")) {
			this.frm.add_custom_button(__('Sync FBR POS Invoice'), function () {
				me.sync_fbr_pos_invoice();
			});
		}

		if (
			doc.docstatus == 1
			&& doc.project
			&& doc.__onload?.can_make_vehicle_gate_pass
			&& frappe.model.can_create("Vehicle Gate Pass")
		) {
			this.frm.add_custom_button(__('Vehicle Gate Pass'), function () {
				me.make_vehicle_gate_pass();
			});
		}

		this.show_general_ledger();
		if(doc.update_stock) {
			this.show_stock_ledger();
		}

		me.add_update_customer_name_button();

		this.add_view_gross_profit_button();

		if (me.frm.doc.docstatus == 0) {
			me.add_get_latest_price_button();
			if (erpnext.utils.has_valuation_read_permission()) {
				me.add_set_rate_as_cost_button();
			}
		}
		if (me.frm.doc.docstatus == 1) {
			me.add_update_price_list_button();
		}

		if (
			doc.docstatus == 1
			&& doc.outstanding_amount != 0
			&& (!doc.is_return || !doc.return_against)
			&& (frappe.model.can_create("Payment Entry") || frappe.model.can_create("Journal Entry"))
		) {
			me.frm.add_custom_button(__('Payment'), () => this.make_payment_entry(),
				__('Create'));
			me.frm.page.set_inner_btn_group_as_primary(__('Create'));
		}

		if (doc.docstatus == 1 && !doc.is_return) {
			let is_delivered_by_supplier = me.frm.doc.items.some((item) => item.is_delivered_by_supplier);

			if (
				(doc.outstanding_amount >= 0 || Math.abs(flt(doc.outstanding_amount)) < flt(doc.grand_total))
				&& frappe.model.can_create("Sales Invoice")
			) {
				me.frm.add_custom_button(__('Return / Credit Note'),
					() => this.make_sales_return(), __('Create'));
				me.frm.page.set_inner_btn_group_as_primary(__('Create'));
			}

			if (!doc.update_stock) {
				// show Make Delivery Note button only if Sales Invoice is not created from Delivery Note
				let from_delivery_note = me.frm.doc.items.some((item) => item.delivery_note);

				if (!from_delivery_note && !is_delivered_by_supplier && frappe.model.can_create("Delivery Note")) {
					me.frm.add_custom_button(__('Delivery'), me.frm.cscript['Make Delivery Note'],
						__('Create'));
				}
			}

			if (doc.outstanding_amount > 0 && frappe.model.can_create("Payment Request")) {
				me.frm.add_custom_button(__('Payment Request'), function() {
					me.make_payment_request();
				}, __('Create'));
			}

			if (doc.docstatus === 1 && frappe.model.can_create("Maintenance Schedule")) {
				me.frm.add_custom_button(__('Maintenance Schedule'), function () {
					me.frm.cscript.make_maintenance_schedule();
				}, __('Create'));
			}

			if (!doc.auto_repeat && frappe.model.can_create("Auto Repeat")) {
				me.frm.add_custom_button(__('Subscription'), function() {
					erpnext.utils.make_subscription(doc.doctype, doc.name)
				}, __('Create'))
			}
		}

		// Show buttons only when pos view is active
		if (doc.docstatus == 0 && this.frm.page.current_view_name != "pos") {
			if (frappe.model.can_read("Delivery Note")) {
				me.frm.add_custom_button(__('Delivery Note'), function () {
					me.get_items_from_delivery_note();
				}, __("Get Items From"));
			}

			if (!doc.is_return) {
				if (frappe.model.can_read("Sales Order")) {
					me.frm.add_custom_button(__('Sales Order'), function () {
						me.get_items_from_sales_order();
					}, __("Get Items From"));
				}

				if (frappe.model.can_read("Quotation")) {
					me.frm.add_custom_button(__('Quotation'), function () {
						me.get_items_from_quotation();
					}, __("Get Items From"));
				}

				if (frappe.model.can_read("Packing Slip")) {
					me.frm.add_custom_button(__('Packing Slip'), function () {
						me.get_items_from_packing_slip("Sales Invoice");
					}, __("Get Items From"));
				}
			}

			if (frappe.model.can_read("Project")) {
				me.frm.add_custom_button(__('Projects'), function () {
					me.get_items_from_project();
				}, __("Get Items From"));
			}

			this.add_get_applicable_items_button();
			this.add_get_project_template_items_button();

			if (frappe.boot.active_domains.includes("Vehicles") && frappe.model.can_read("Vehicle Booking Order")) {
				me.frm.add_custom_button(__('Vehicle Booking Order'), function() {
					me.get_items_from_vehicle_booking_order();
				}, __("Get Items From"));
			}
		}

		this.set_default_print_format();

		if (doc.docstatus == 1 && !doc.inter_company_reference) {
			if (me.frm.doc.__onload?.is_internal_customer) {
				me.frm.add_custom_button("Inter Company Invoice", function() {
					me.make_inter_company_invoice();
				}, __('Create'));
			}
		}

		this.frm.set_indicator_formatter('item_code', function(doc, parent) {
			if (doc.docstatus === 0) {
				if (parent.update_stock && !parent.is_return) {
					if (!doc.is_stock_item) {
						return "blue";
					} else if (!doc.actual_qty) {
						return "red";
					} else if (doc.actual_qty < doc.stock_qty) {
						return "orange";
					} else {
						return "green";
					}
				}
			} else {
				if (!parent.is_return) {
					if (doc.returned_qty) {
						return "yellow";
					} else if (doc.base_returned_amount) {
						return "grey";
					}
				}
			}
		});
	}

	sync_fbr_pos_invoice() {
		var me = this;
		frappe.call({
			"method": "erpnext.erpnext_integrations.fbr_pos_integration.sync_fbr_pos_invoice",
			"args": {
				"sales_invoice": this.frm.doc.name
			},
			"freeze": 1,
			"freeze_message": __("Syncing with FBR POS Service"),
			callback: function(r) {
				if (!r.exc && r.message) {
					me.frm.reload_doc();
				}
			}
		});
	}

	make_vehicle_gate_pass() {
		if (this.frm.doc.project) {
			return frappe.call({
				method: "erpnext.projects.doctype.project.project.get_vehicle_gate_pass",
				args: {
					"project": this.frm.doc.project,
					"purpose": "Service - Vehicle Delivery",
					"sales_invoice": this.frm.doc.name
				},
				callback: function (r) {
					if (!r.exc) {
						var doclist = frappe.model.sync(r.message);
						frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
					}
				}
			});
		}
	}

	make_maintenance_schedule() {
		frappe.model.open_mapped_doc({
			method: "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_maintenance_schedule",
			frm: cur_frm
		})
	}

	add_view_gross_profit_button() {
		if (this.frm.doc.docstatus === 1) {
			this.frm.add_custom_button(__("Gross Profit"), () => {
				frappe.route_options = {
					sales_invoice: this.frm.doc.name,
					from_date: this.frm.doc.posting_date,
					to_date: this.frm.doc.posting_date,
					company: this.frm.doc.company,
				};
				frappe.set_route("query-report", "Gross Profit");
			}, __("View"));
		}
	}

	on_submit(doc, dt, dn) {
		var me = this;

		if (frappe.get_route()[0] != 'Form') {
			return
		}

		$.each(doc["items"], function(i, row) {
			if(row.delivery_note) frappe.model.clear_doc("Delivery Note", row.delivery_note)
		})
	}

	set_default_print_format() {
		// set default print format to POS type or Credit Note
		if(cur_frm.doc.is_pos) {
			if(cur_frm.pos_print_format) {
				cur_frm.meta._default_print_format = cur_frm.meta.default_print_format;
				cur_frm.meta.default_print_format = cur_frm.pos_print_format;
			}
		} else if(cur_frm.doc.is_return && !cur_frm.meta.default_print_format) {
			if(cur_frm.return_print_format) {
				cur_frm.meta._default_print_format = cur_frm.meta.default_print_format;
				cur_frm.meta.default_print_format = cur_frm.return_print_format;
			}
		} else {
			if(cur_frm.meta._default_print_format) {
				cur_frm.meta.default_print_format = cur_frm.meta._default_print_format;
				cur_frm.meta._default_print_format = null;
			} else if(in_list([cur_frm.pos_print_format, cur_frm.return_print_format], cur_frm.meta.default_print_format)) {
				cur_frm.meta.default_print_format = null;
				cur_frm.meta._default_print_format = null;
			}
		}
	}

	get_items_from_quotation() {
		var me = this;

		erpnext.utils.map_current_doc({
			method: "erpnext.selling.doctype.quotation.quotation.make_sales_invoice",
			source_doctype: "Quotation",
			target: me.frm,
			setters: [
				{
					fieldtype: 'Link',
					label: __('Customer'),
					options: 'Customer',
					fieldname: 'party_name',
					default: me.frm.doc.customer || undefined,
				},
				{
					fieldtype: 'Link',
					label: __('Project'),
					options: 'Project',
					fieldname: 'project',
					default: me.frm.doc.project || undefined,
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
				status: ["!=", "Lost"],
				company: me.frm.doc.company,
				quotation_to: 'Customer',
			}
		});
	}

	get_items_from_sales_order() {
		var me = this;

		erpnext.utils.map_current_doc({
			method: "erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice",
			source_doctype: "Sales Order",
			target: me.frm,
			setters: [
				{
					fieldtype: 'Link',
					label: __('Customer'),
					options: 'Customer',
					fieldname: 'customer',
					default: me.frm.doc.customer || undefined,
				},
				{
					fieldtype: 'Link',
					label: __('Project'),
					options: 'Project',
					fieldname: 'project',
					default: me.frm.doc.project || undefined,
				},
				{
					fieldtype: 'DateRange',
					label: __('Date Range'),
					fieldname: 'transaction_date',
				}
			],
			columns: ['customer_name', 'transaction_date', 'project'],
			get_query: function() {
				var filters = {
					company: me.frm.doc.company,
					claim_billing: cint(me.frm.doc.claim_billing),
				};
				if (me.frm.doc.customer) {
					filters["customer"] = me.frm.doc.customer;
				}

				return {
					query: "erpnext.controllers.queries.get_sales_orders_to_be_billed",
					filters: filters
				};
			},
			args: {
				only_items: cint(me.frm.doc.claim_billing)
			}
		});
	}

	get_items_from_delivery_note() {
		var me = this;

		erpnext.utils.map_current_doc({
			method: "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_invoice",
			source_doctype: "Delivery Note",
			target: me.frm,
			setters: [
				{
					fieldtype: 'Link',
					label: __('Customer'),
					options: 'Customer',
					fieldname: 'customer',
					default: me.frm.doc.customer || undefined,
				},
				{
					fieldtype: 'Link',
					label: __('Project'),
					options: 'Project',
					fieldname: 'project',
					default: me.frm.doc.project || undefined,
				},
				{
					fieldtype: 'DateRange',
					label: __('Date Range'),
					fieldname: 'posting_date',
				}
			],
			columns: ['customer_name', 'posting_date', 'project'],
			get_query: function() {
				var filters = {
					company: me.frm.doc.company,
					is_return: cint(me.frm.doc.is_return),
					claim_billing: cint(me.frm.doc.claim_billing),
				};
				if(me.frm.doc.customer) {
					filters["customer"] = me.frm.doc.customer;
				}

				return {
					query: "erpnext.controllers.queries.get_delivery_notes_to_be_billed",
					filters: filters
				};
			},
			args: {
				only_items: cint(me.frm.doc.claim_billing)
			}
		});
	}

	get_items_from_vehicle_booking_order() {
		let me = this;
		let doc = {orders: []};

		let dialog = new frappe.ui.Dialog({
			title: __("Get Vehicle Booking Orders"),
			doc: doc,
			fields: [
				{
					label: __('From Date'),
					fieldname: 'from_date',
					fieldtype: 'Date',
				},
				{
					label: __('To Date'),
					fieldname: 'to_date',
					fieldtype: 'Date',
				},
				{
					fieldtype: "Column Break",
				},
				{
					fieldtype: "Link",
					label: __("Vehicle Item Code"),
					fieldname: "item_code",
					options: "Item",
					onchange: function () {
						let item_code = dialog.get_value('item_code');
						if (item_code) {
							frappe.db.get_value("Item", item_code, 'item_name', function (r) {
								if (r) {
									dialog.set_value('item_name', r.item_name);
								}
							});
						} else {
							dialog.set_value("item_name", "");
						}
					},
					get_query: function () {
						return erpnext.queries.item({ 'is_vehicle': 1, 'include_in_vehicle_booking': 1, "include_templates": 1 });
					}
				},
				{
					fieldtype: "Data",
					label: __("Vehicle Item Name"),
					fieldname: "item_name",
					read_only: 1,
				},
				{
					fieldtype: "Button",
					label: __("Get Vehicle Booking Orders"),
					fieldname: "get_vbos",
					click: function () {
						let item_code = dialog.get_value('item_code');
						let from_date = dialog.get_value('from_date');
						let to_date = dialog.get_value('to_date');
						if (!from_date || !to_date) {
							frappe.throw(__("From Date and To Date is mandatory"));
						}

						return frappe.call({
							method: "erpnext.vehicles.doctype.vehicle_booking_order.vehicle_booking_order.get_vbos_for_sales_invoice",
							args: {
								item_code: item_code,
								from_date: from_date,
								to_date: to_date,
							},
							callback: function (r) {
								if (r.message) {
									doc.orders.length = 0;
									for (let vbo of r.message) {
										doc.orders.push({
											"vehicle_booking_order": vbo
										});
									}
									dialog.fields_dict.orders.refresh();
								}
							}
						});
					}
				},
				{
					fieldtype: "Section Break",
				},
				{
					label: __("Vehicle Booking Orders"),
					fieldname: "orders",
					fieldtype: "Table",
					reqd: 1,
					fields: [
						{
							label: __("Vehicle Booking Order"),
							fieldname: "vehicle_booking_order",
							fieldtype: "Link",
							options: "Vehicle Booking Order",
							reqd: 1,
							in_list_view: 1,
							get_query: function () {
								return {
									filters: {docstatus: 1}
								};
							}
						},
					],
					data: doc.orders,
				},
			],
			primary_action: function () {
				let values = dialog.get_values();
				let vbos = values.orders.map(row => row.vehicle_booking_order);
				return me.frm.call({
					doc: me.frm.doc,
					method: "add_vehicle_booking_commission_items",
					args: {
						vehicle_booking_orders: vbos,
					},
					callback: function(r) {
						dialog.hide();
					}
				});
			},
			primary_action_label: __('Get Commission Items')
		});

		dialog.show();
	}

	get_items_from_project() {
		var me = this;

		me.frm.set_value('claim_billing', 1);

		erpnext.utils.map_current_doc({
			method: "erpnext.projects.doctype.project.project.make_sales_invoice",
			source_doctype: "Project",
			target: me.frm,
			setters: [
				{
					label: __("Customer"),
					fieldname: 'customer',
					fieldtype: 'Link',
					options: 'Customer',
					default: me.frm.doc.bill_to || me.frm.doc.customer || undefined,
				},
				{
					label: __("Project Type"),
					fieldname: 'project_type',
					fieldtype: 'Link',
					options: 'Project Type',
				},
				{
					fieldtype: 'DateRange',
					label: __('Date Range'),
					fieldname: 'project_date',
				}
			],
			columns: ['customer_name', 'project_date', 'project_type'],
			get_query: function() {
				var filters = {
					company: me.frm.doc.company,
					claim_billing: 1
				};
				if(me.frm.doc.bill_to || me.frm.doc.customer) {
					filters["customer"] = me.frm.doc.bill_to || me.frm.doc.customer;
				}

				return {
					query: "erpnext.controllers.queries.get_projects_to_be_billed",
					filters: filters
				};
			},
			args: {
				claim_billing: 1
			}
		});
	}

	tc_name() {
		this.get_terms();
	}

	customer() {
		var me = this;

		if(this.frm.doc.customer) {
			frappe.call({
				"method": "erpnext.accounts.doctype.sales_invoice.sales_invoice.get_loyalty_programs",
				"args": {
					"customer": this.frm.doc.customer
				},
				callback: function(r) {
					if(r.message && r.message.length) {
						select_loyalty_program(me.frm, r.message);
					}
				}
			});
		}

		return this.frm.set_value("bill_to", this.frm.doc.customer);
	}

	bill_to() {
		if (this.frm.doc.is_pos){
			var pos_profile = this.frm.doc.pos_profile;
		}

		this.set_dynamic_link();

		var me = this;
		if(this.frm.updating_party_details) return;
		return erpnext.utils.get_party_details(this.frm,
			"erpnext.accounts.party.get_party_details", {
				posting_date: this.frm.doc.posting_date,
				party: this.frm.doc.customer,
				party_type: "Customer",
				bill_to: this.frm.doc.bill_to,
				account: this.frm.doc.debit_to,
				price_list: this.frm.doc.selling_price_list,
				pos_profile: pos_profile
			}, function() {
				me.apply_pricing_rule();
			});
	}

	make_inter_company_invoice() {
		frappe.model.open_mapped_doc({
			method: "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_inter_company_purchase_invoice",
			frm: this.frm
		});
	}

	debit_to() {
		var me = this;
		if(this.frm.doc.debit_to) {
			me.frm.call({
				method: "frappe.client.get_value",
				args: {
					doctype: "Account",
					fieldname: "account_currency",
					filters: { name: me.frm.doc.debit_to },
				},
				callback: function(r, rt) {
					if(r.message) {
						me.frm.set_value("party_account_currency", r.message.account_currency);
						me.set_dynamic_labels();
					}
				}
			});
		}
	}

	allocated_amount() {
		this.calculate_total_advance();
		this.frm.refresh_fields();
	}

	write_off_outstanding_amount_automatically() {
		var grand_total = this.frm.doc.rounded_total || this.frm.doc.grand_total;
		if(cint(this.frm.doc.write_off_outstanding_amount_automatically)) {
			frappe.model.round_floats_in(this.frm.doc, ["grand_total", "paid_amount"]);
			// this will make outstanding amount 0
			this.frm.doc.write_off_amount = flt(grand_total - this.frm.doc.paid_amount - this.frm.doc.total_advance,
				precision("write_off_amount"));
			this.set_in_company_currency(this.frm.doc, ["write_off_amount"]);
			this.frm.toggle_enable("write_off_amount", false);

		} else {
			this.frm.toggle_enable("write_off_amount", true);
		}

		this.calculate_outstanding_amount(false);
		this.frm.refresh_fields();
	}

	write_off_amount() {
		this.set_in_company_currency(this.frm.doc, ["write_off_amount"]);
		this.write_off_outstanding_amount_automatically();
	}

	items_add(doc, cdt, cdn) {
		var row = frappe.get_doc(cdt, cdn);
		this.frm.script_manager.copy_from_first_row("items", row, ["income_account"]);

		if (!this.frm.doc.claim_billing) {
			row.project = this.frm.doc.project;
		}
	}

	set_dynamic_labels() {
		this.hide_fields(this.frm.doc);
		this.set_project_read_only();
		super.set_dynamic_labels();
	}

	claim_billing() {
		this.set_project_read_only();
		if (this.frm.doc.claim_billing) {
			this.frm.set_value("project", null);
		} else {
			this.copy_project_in_items();
		}
	}

	set_project_read_only() {
		this.frm.set_df_property('project', 'read_only', cint(this.frm.doc.claim_billing));
	}

	copy_project_in_items() {
		var me = this;
		if (!me.frm.doc.claim_billing) {
			$.each(me.frm.doc.items || [], function (i, item) {
				item.project = me.frm.doc.project;
				refresh_field("project", item.name, "items");
			});
		}
	}

	items_on_form_rendered() {
		erpnext.setup_serial_no();
	}

	packed_items_on_form_rendered() {
		erpnext.setup_serial_no();
	}

	make_sales_return() {
		var me = this;
		var has_stock_item = me.frm.doc.items.some(d => d.is_stock_item);
		var has_order = me.frm.doc.items.some(d => d.sales_order || d.delivery_note);

		if (has_stock_item || has_order) {
			var fields = [];
			if (has_stock_item) {
				fields.push({
					"label" : "Update Stock",
					"description": "If 'Yes', then stock will be returned along with party balance",
					"fieldname": "update_stock",
					"fieldtype": "Select",
					"options": "\nYes\nNo",
					"reqd": 1,
				});
			}
			if (has_order) {
				fields.push({
					"label" : "Reopen Sales Order / Delivery Note",
					"description": "If 'Yes', Sales Orders and Delivery Notes will be reopened for billing again",
					"fieldname": "reopen_order",
					"fieldtype": "Select",
					"options": "\nYes\nNo",
					"reqd": 1,
				});
			}

			var dialog = new frappe.ui.Dialog({
				title: __('Credit Note Options'),
				fields: fields,
				primary_action: function() {
					var options = dialog.get_values();
					me._make_sales_return(options);
				},
				primary_action_label: __('Create')
			});
			dialog.show();
		} else {
			this._make_sales_return();
		}
	}

	_make_sales_return(options) {
		frappe.model.open_mapped_doc({
			method: "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_return",
			frm: this.frm,
			args: options,
		});
	}

	asset(frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if(row.asset) {
			frappe.call({
				method: erpnext.assets.doctype.asset.depreciation.get_disposal_account_and_cost_center,
				args: {
					"company": frm.doc.company
				},
				callback: function(r, rt) {
					frappe.model.set_value(cdt, cdn, "income_account", r.message[0]);
					frappe.model.set_value(cdt, cdn, "cost_center", r.message[1]);
				}
			})
		}
	}

	is_pos(frm) {
		this.set_pos_data();
	}

	pos_profile() {
		this.frm.doc.taxes = []
		this.set_pos_data();
	}

	set_pos_data() {
		if(this.frm.doc.is_pos) {
			this.frm.set_value("allocate_advances_automatically", 0);
			if(!this.frm.doc.company) {
				this.frm.set_value("is_pos", 0);
				frappe.msgprint(__("Please specify Company to proceed"));
			} else {
				var me = this;
				return this.frm.call({
					doc: me.frm.doc,
					method: "set_missing_values",
					callback: function(r) {
						if(!r.exc) {
							if(r.message && r.message.print_format) {
								me.frm.pos_print_format = r.message.print_format;
							}
							me.frm.script_manager.trigger("update_stock");
							if(me.frm.doc.taxes_and_charges) {
								me.frm.script_manager.trigger("taxes_and_charges");
							}

							frappe.model.set_default_values(me.frm.doc);
							me.set_dynamic_labels();
							me.calculate_taxes_and_totals();
						}
					}
				});
			}
		}
		else this.frm.trigger("refresh");
	}

	amount() {
		this.write_off_outstanding_amount_automatically()
	}

	change_amount() {
		if(this.frm.doc.paid_amount > this.frm.doc.grand_total){
			this.calculate_write_off_amount();
		}else {
			this.frm.set_value("change_amount", 0.0);
			this.frm.set_value("base_change_amount", 0.0);
		}

		this.frm.refresh_fields();
	}

	loyalty_amount() {
		this.calculate_outstanding_amount();
		this.frm.refresh_field("outstanding_amount");
		this.frm.refresh_field("paid_amount");
		this.frm.refresh_field("base_paid_amount");
	}
};

// for backward compatibility: combine new and previous states
extend_cscript(cur_frm.cscript, new erpnext.accounts.SalesInvoiceController({frm: cur_frm}));

// Hide Fields
// ------------
cur_frm.cscript.hide_fields = function(doc, refresh) {
	// India related fields
	var hidden = cint(frappe.boot.sysdefaults.country != 'India');
	this.frm.set_df_property("c_form_applicable", "hidden", hidden);
	this.frm.set_df_property("c_form_no", "hidden", hidden);

	this.frm.toggle_enable("write_off_amount", !!!cint(doc.write_off_outstanding_amount_automatically));

	if (refresh) {
		cur_frm.refresh_fields();
	}
}

cur_frm.cscript.update_stock = function(doc, dt, dn) {
	cur_frm.cscript.hide_fields(doc, true);
	this.frm.fields_dict.items.grid.toggle_reqd("item_code", doc.update_stock? true: false)
	this.show_hide_select_batch_button();
}

cur_frm.cscript['Make Delivery Note'] = function() {
	frappe.model.open_mapped_doc({
		method: "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_delivery_note",
		frm: cur_frm
	})
}

cur_frm.fields_dict.cash_bank_account.get_query = function(doc) {
	return {
		filters: [
			["Account", "account_type", "in", ["Cash", "Bank"]],
			["Account", "root_type", "=", "Asset"],
			["Account", "is_group", "=",0],
			["Account", "company", "=", doc.company]
		]
	}
}

cur_frm.fields_dict.write_off_account.get_query = function(doc) {
	return{
		filters:{
			'report_type': 'Profit and Loss',
			'is_group': 0,
			'company': doc.company
		}
	}
}

// Write off cost center
//-----------------------
cur_frm.fields_dict.write_off_cost_center.get_query = function(doc) {
	return{
		filters:{
			'is_group': 0,
			'company': doc.company
		}
	}
}

// Income Account in Details Table
// --------------------------------
cur_frm.set_query("income_account", "items", function(doc) {
	return{
		query: "erpnext.controllers.queries.get_income_account",
		filters: {'company': doc.company}
	}
});


// Cost Center in Details Table
// -----------------------------
cur_frm.fields_dict["items"].grid.get_field("cost_center").get_query = function(doc) {
	return {
		filters: {
			'company': doc.company,
			"is_group": 0
		}
	}
}

cur_frm.cscript.income_account = function(doc, cdt, cdn) {
	erpnext.utils.copy_value_in_all_rows(doc, cdt, cdn, "items", "income_account");
}

cur_frm.cscript.expense_account = function(doc, cdt, cdn) {
	erpnext.utils.copy_value_in_all_rows(doc, cdt, cdn, "items", "expense_account");
}

cur_frm.set_query("debit_to", function(doc) {
	return {
		filters: {
			'account_type': 'Receivable',
			'is_group': 0,
			'company': doc.company
		}
	}
});

cur_frm.set_query("asset", "items", function(doc, cdt, cdn) {
	var d = locals[cdt][cdn];
	return {
		filters: [
			["Asset", "item_code", "=", d.item_code],
			["Asset", "docstatus", "=", 1],
			["Asset", "status", "in", ["Submitted", "Partially Depreciated", "Fully Depreciated"]],
			["Asset", "company", "=", doc.company]
		]
	}
});

frappe.ui.form.on('Sales Invoice', {
	setup: function(frm){
		frm.add_fetch('payment_term', 'invoice_portion', 'invoice_portion');
		frm.add_fetch('payment_term', 'description', 'description');

		frm.set_query("account_for_change_amount", function() {
			return {
				filters: {
					account_type: ['in', ["Cash", "Bank"]],
					company: frm.doc.company,
					is_group: 0
				}
			};
		});

		frm.set_query("cost_center", function() {
			return {
				filters: {
					company: frm.doc.company,
					is_group: 0
				}
			};
		});

		frm.custom_make_buttons = {
			'Delivery Note': 'Delivery',
			'Sales Invoice': 'Return / Credit Note',
			'Payment Request': 'Payment Request',
			'Invoice Discounting': 'Invoice Discounting',
			'Payment Entry': 'Payment',
			'Auto Repeat': 'Subscription',
			'Vehicle Gate Pass': 'Vehicle Gate Pass',
		};

		frm.set_query("time_sheet", "timesheets", function(doc) {
			let filters = {'docstatus': 1};
			if (doc.project) {
				filters.project = doc.project;
			}

			return {
				filters: filters
			};
		});

		// expense account
		frm.fields_dict['items'].grid.get_field('expense_account').get_query = function(doc) {
			if (erpnext.is_perpetual_inventory_enabled(doc.company)) {
				return {
					filters: {
						'report_type': 'Profit and Loss',
						'company': doc.company,
						"is_group": 0
					}
				}
			}
		}

		frm.fields_dict['items'].grid.get_field('deferred_revenue_account').get_query = function(doc) {
			return {
				filters: {
					'root_type': 'Liability',
					'company': doc.company,
					"is_group": 0
				}
			}
		}

		frm.set_query('pos_profile', function(doc) {
			if(!doc.company) {
				frappe.throw(_('Please set Company'));
			}

			return {
				query: 'erpnext.accounts.doctype.pos_profile.pos_profile.pos_profile_query',
				filters: {
					company: doc.company
				}
			};
		});

		// set get_query for loyalty redemption account
		frm.fields_dict["loyalty_redemption_account"].get_query = function() {
			return {
				filters:{
					"company": frm.doc.company,
					"is_group": 0
				}
			}
		};

		// set get_query for loyalty redemption cost center
		frm.fields_dict["loyalty_redemption_cost_center"].get_query = function() {
			return {
				filters:{
					"company": frm.doc.company,
					"is_group": 0
				}
			}
		};
	},
	// When multiple companies are set up. in case company name is changed set default company address
	company:function(frm){
		if (frm.doc.company)
		{
			frappe.call({
				method:"erpnext.setup.doctype.company.company.get_default_company_address",
				args:{name:frm.doc.company, existing_address: frm.doc.company_address},
				callback: function(r){
					if (r.message){
						frm.set_value("company_address",r.message)
					}
					else {
						frm.set_value("company_address","")
					}
				}
			})
		}
	},

	project: function(frm) {
		frm.call({
			method: "add_timesheet_data",
			doc: frm.doc,
			callback: function(r, rt) {
				refresh_field(['timesheets'])
			}
		})
	},

	onload: function(frm) {
		frm.redemption_conversion_factor = null;
	},

	redeem_loyalty_points: function(frm) {
		frm.events.get_loyalty_details(frm);
	},

	loyalty_points: function(frm) {
		if (frm.redemption_conversion_factor) {
			frm.events.set_loyalty_points(frm);
		} else {
			frappe.call({
				method: "erpnext.accounts.doctype.loyalty_program.loyalty_program.get_redeemption_factor",
				args: {
					"loyalty_program": frm.doc.loyalty_program
				},
				callback: function(r) {
					if (r) {
						frm.redemption_conversion_factor = r.message;
						frm.events.set_loyalty_points(frm);
					}
				}
			});
		}
	},

	get_loyalty_details: function(frm) {
		if (frm.doc.customer && frm.doc.redeem_loyalty_points) {
			frappe.call({
				method: "erpnext.accounts.doctype.loyalty_program.loyalty_program.get_loyalty_program_details",
				args: {
					"customer": frm.doc.customer,
					"loyalty_program": frm.doc.loyalty_program,
					"expiry_date": frm.doc.posting_date,
					"company": frm.doc.company
				},
				callback: function(r) {
					if (r) {
						frm.set_value("loyalty_redemption_account", r.message.expense_account);
						frm.set_value("loyalty_redemption_cost_center", r.message.cost_center);
						frm.redemption_conversion_factor = r.message.conversion_factor;
					}
				}
			});
		}
	},

	set_loyalty_points: function(frm) {
		if (frm.redemption_conversion_factor) {
			let loyalty_amount = flt(frm.redemption_conversion_factor*flt(frm.doc.loyalty_points), precision("loyalty_amount"));
			var remaining_amount = flt(frm.doc.grand_total) - flt(frm.doc.total_advance) - flt(frm.doc.write_off_amount);
			if (frm.doc.grand_total && (remaining_amount < loyalty_amount)) {
				let redeemable_points = parseInt(remaining_amount/frm.redemption_conversion_factor);
				frappe.throw(__("You can only redeem max {0} points in this order.",[redeemable_points]));
			}
			frm.set_value("loyalty_amount", loyalty_amount);
		}
	},

	// Healthcare
	patient: function(frm) {
		if (frappe.boot.active_domains.includes("Healthcare")){
			if(frm.doc.patient){
				frappe.call({
					method: "frappe.client.get_value",
					args:{
						doctype: "Patient",
						filters: {"name": frm.doc.patient},
						fieldname: "customer"
					},
					callback:function(patient_customer) {
						if(patient_customer){
							frm.set_value("customer", patient_customer.message.customer);
							frm.refresh_fields();
						}
					}
				});
			}
			else{
					frm.set_value("customer", '');
			}
		}
	},
	refresh: function(frm) {
		if (frappe.boot.active_domains.includes("Healthcare")){
			frm.set_df_property("patient", "hidden", 0);
			frm.set_df_property("patient_name", "hidden", 0);
			frm.set_df_property("ref_practitioner", "hidden", 0);
			if (cint(frm.doc.docstatus==0) && cur_frm.page.current_view_name!=="pos" && !frm.doc.is_return) {
				frm.add_custom_button(__('Healthcare Services'), function() {
					get_healthcare_services_to_invoice(frm);
				},"Get Items From");
				frm.add_custom_button(__('Prescriptions'), function() {
					get_drugs_to_invoice(frm);
				},"Get Items From");
			}
		}
		else{
			frm.set_df_property("patient", "hidden", 1);
			frm.set_df_property("patient_name", "hidden", 1);
			frm.set_df_property("ref_practitioner", "hidden", 1);
		}
	},

	create_invoice_discounting: function(frm) {
		frappe.model.open_mapped_doc({
			method: "erpnext.accounts.doctype.sales_invoice.sales_invoice.create_invoice_discounting",
			frm: frm
		});
	}
})

frappe.ui.form.on('Sales Invoice Timesheet', {
	time_sheet: function(frm, cdt, cdn){
		var d = locals[cdt][cdn];
		if(d.time_sheet) {
			frappe.call({
				method: "erpnext.projects.doctype.timesheet.timesheet.get_timesheet_data",
				args: {
					'name': d.time_sheet,
					'project': frm.doc.project || null
				},
				callback: function(r, rt) {
					if(r.message){
						data = r.message;
						frappe.model.set_value(cdt, cdn, "billing_hours", data.billing_hours);
						frappe.model.set_value(cdt, cdn, "billing_amount", data.billing_amount);
						frappe.model.set_value(cdt, cdn, "timesheet_detail", data.timesheet_detail);
						calculate_total_billing_amount(frm)
					}
				}
			})
		}
	}
})

var calculate_total_billing_amount =  function(frm) {
	var doc = frm.doc;

	doc.total_billing_amount = 0.0
	if(doc.timesheets) {
		$.each(doc.timesheets, function(index, data){
			doc.total_billing_amount += data.billing_amount
		})
	}

	refresh_field('total_billing_amount')
}

var select_loyalty_program = function(frm, loyalty_programs) {
	var dialog = new frappe.ui.Dialog({
		title: __("Select Loyalty Program"),
		fields: [
			{
				"label": __("Loyalty Program"),
				"fieldname": "loyalty_program",
				"fieldtype": "Select",
				"options": loyalty_programs,
				"default": loyalty_programs[0]
			}
		]
	});

	dialog.set_primary_action(__("Set"), function() {
		dialog.hide();
		return frappe.call({
			method: "frappe.client.set_value",
			args: {
				doctype: "Customer",
				name: frm.doc.customer,
				fieldname: "loyalty_program",
				value: dialog.get_value("loyalty_program"),
			},
			callback: function(r) { }
		});
	});

	dialog.show();
}

// Healthcare
var get_healthcare_services_to_invoice = function(frm) {
	var me = this;
	let selected_patient = '';
	var dialog = new frappe.ui.Dialog({
		title: __("Get Items from Healthcare Services"),
		fields:[
			{
				fieldtype: 'Link',
				options: 'Patient',
				label: 'Patient',
				fieldname: "patient",
				reqd: true
			},
			{ fieldtype: 'Section Break'	},
			{ fieldtype: 'HTML', fieldname: 'results_area' }
		]
	});
	var $wrapper;
	var $results;
	var $placeholder;
	dialog.set_values({
		'patient': frm.doc.patient
	});
	dialog.fields_dict["patient"].df.onchange = () => {
		var patient = dialog.fields_dict.patient.input.value;
		if(patient && patient!=selected_patient){
			selected_patient = patient;
			var method = "erpnext.healthcare.utils.get_healthcare_services_to_invoice";
			var args = {patient: patient};
			var columns = (["service", "reference_name", "reference_type"]);
			get_healthcare_items(frm, true, $results, $placeholder, method, args, columns);
		}
		else if(!patient){
			selected_patient = '';
			$results.empty();
			$results.append($placeholder);
		}
	}
	$wrapper = dialog.fields_dict.results_area.$wrapper.append(`<div class="results"
		style="border: 1px solid #d1d8dd; border-radius: 3px; height: 300px; overflow: auto;"></div>`);
	$results = $wrapper.find('.results');
	$placeholder = $(`<div class="multiselect-empty-state">
				<span class="text-center" style="margin-top: -40px;">
					<i class="fa fa-2x fa-heartbeat text-extra-muted"></i>
					<p class="text-extra-muted">No billable Healthcare Services found</p>
				</span>
			</div>`);
	$results.on('click', '.list-item--head :checkbox', (e) => {
		$results.find('.list-item-container .list-row-check')
			.prop("checked", ($(e.target).is(':checked')));
	});
	set_primary_action(frm, dialog, $results, true);
	dialog.show();
};

var get_healthcare_items = function(frm, invoice_healthcare_services, $results, $placeholder, method, args, columns) {
	var me = this;
	$results.empty();
	frappe.call({
		method: method,
		args: args,
		callback: function(data) {
			if(data.message){
				$results.append(make_list_row(columns, invoice_healthcare_services));
				for(let i=0; i<data.message.length; i++){
					$results.append(make_list_row(columns, invoice_healthcare_services, data.message[i]));
				}
			}else {
				$results.append($placeholder);
			}
		}
	});
}

var make_list_row= function(columns, invoice_healthcare_services, result={}) {
	var me = this;
	// Make a head row by default (if result not passed)
	let head = Object.keys(result).length === 0;
	let contents = ``;
	columns.forEach(function(column) {
		contents += `<div class="list-item__content ellipsis">
			${
				head ? `<span class="ellipsis">${__(frappe.model.unscrub(column))}</span>`

				:(column !== "name" ? `<span class="ellipsis">${__(result[column])}</span>`
					: `<a class="list-id ellipsis">
						${__(result[column])}</a>`)
			}
		</div>`;
	})

	let $row = $(`<div class="list-item">
		<div class="list-item__content" style="flex: 0 0 10px;">
			<input type="checkbox" class="list-row-check" ${result.checked ? 'checked' : ''}>
		</div>
		${contents}
	</div>`);

	$row = list_row_data_items(head, $row, result, invoice_healthcare_services);
	return $row;
};

var set_primary_action= function(frm, dialog, $results, invoice_healthcare_services) {
	var me = this;
	dialog.set_primary_action(__('Add'), function() {
		let checked_values = get_checked_values($results);
		if(checked_values.length > 0){
			if(invoice_healthcare_services) {
				frm.set_value("patient", dialog.fields_dict.patient.input.value);
			}
			frm.set_value("items", []);
			add_to_item_line(frm, checked_values, invoice_healthcare_services);
			dialog.hide();
		}
		else{
			if(invoice_healthcare_services){
				frappe.msgprint(__("Please select Healthcare Service"));
			}
			else{
				frappe.msgprint(__("Please select Drug"));
			}
		}
	});
};

var get_checked_values= function($results) {
	return $results.find('.list-item-container').map(function() {
		let checked_values = {};
		if ($(this).find('.list-row-check:checkbox:checked').length > 0 ) {
			checked_values['dn'] = $(this).attr('data-dn');
			checked_values['dt'] = $(this).attr('data-dt');
			checked_values['item'] = $(this).attr('data-item');
			if($(this).attr('data-rate') != 'undefined'){
				checked_values['rate'] = $(this).attr('data-rate');
			}
			else{
				checked_values['rate'] = false;
			}
			if($(this).attr('data-income-account') != 'undefined'){
				checked_values['income_account'] = $(this).attr('data-income-account');
			}
			else{
				checked_values['income_account'] = false;
			}
			if($(this).attr('data-qty') != 'undefined'){
				checked_values['qty'] = $(this).attr('data-qty');
			}
			else{
				checked_values['qty'] = false;
			}
			if($(this).attr('data-description') != 'undefined'){
				checked_values['description'] = $(this).attr('data-description');
			}
			else{
				checked_values['description'] = false;
			}
			return checked_values;
		}
	}).get();
};

var get_drugs_to_invoice = function(frm) {
	var me = this;
	let selected_encounter = '';
	var dialog = new frappe.ui.Dialog({
		title: __("Get Items from Prescriptions"),
		fields:[
			{ fieldtype: 'Link', options: 'Patient', label: 'Patient', fieldname: "patient", reqd: true },
			{ fieldtype: 'Link', options: 'Patient Encounter', label: 'Patient Encounter', fieldname: "encounter", reqd: true,
				description:'Quantity will be calculated only for items which has "Nos" as UoM. You may change as required for each invoice item.',
				get_query: function(doc) {
					return {
						filters: { patient: dialog.get_value("patient"), docstatus: 1 }
					};
				}
			},
			{ fieldtype: 'Section Break' },
			{ fieldtype: 'HTML', fieldname: 'results_area' }
		]
	});
	var $wrapper;
	var $results;
	var $placeholder;
	dialog.set_values({
		'patient': frm.doc.patient,
		'encounter': ""
	});
	dialog.fields_dict["encounter"].df.onchange = () => {
		var encounter = dialog.fields_dict.encounter.input.value;
		if(encounter && encounter!=selected_encounter){
			selected_encounter = encounter;
			var method = "erpnext.healthcare.utils.get_drugs_to_invoice";
			var args = {encounter: encounter};
			var columns = (["drug_code", "quantity", "description"]);
			get_healthcare_items(frm, false, $results, $placeholder, method, args, columns);
		}
		else if(!encounter){
			selected_encounter = '';
			$results.empty();
			$results.append($placeholder);
		}
	}
	$wrapper = dialog.fields_dict.results_area.$wrapper.append(`<div class="results"
		style="border: 1px solid #d1d8dd; border-radius: 3px; height: 300px; overflow: auto;"></div>`);
	$results = $wrapper.find('.results');
	$placeholder = $(`<div class="multiselect-empty-state">
				<span class="text-center" style="margin-top: -40px;">
					<i class="fa fa-2x fa-heartbeat text-extra-muted"></i>
					<p class="text-extra-muted">No Drug Prescription found</p>
				</span>
			</div>`);
	$results.on('click', '.list-item--head :checkbox', (e) => {
		$results.find('.list-item-container .list-row-check')
			.prop("checked", ($(e.target).is(':checked')));
	});
	set_primary_action(frm, dialog, $results, false);
	dialog.show();
};

var list_row_data_items = function(head, $row, result, invoice_healthcare_services) {
	if(invoice_healthcare_services){
		head ? $row.addClass('list-item--head')
			: $row = $(`<div class="list-item-container"
				data-dn= "${result.reference_name}" data-dt= "${result.reference_type}" data-item= "${result.service}"
				data-rate = ${result.rate}
				data-income-account = "${result.income_account}"
				data-qty = ${result.qty}
				data-description = "${result.description}">
				</div>`).append($row);
	}
	else{
		head ? $row.addClass('list-item--head')
			: $row = $(`<div class="list-item-container"
				data-item= "${result.drug_code}"
				data-qty = ${result.quantity}
				data-description = "${result.description}">
				</div>`).append($row);
	}
	return $row
};

var add_to_item_line = function(frm, checked_values, invoice_healthcare_services){
	if(invoice_healthcare_services){
		frappe.call({
			doc: frm.doc,
			method: "set_healthcare_services",
			args:{
				checked_values: checked_values
			},
			callback: function() {
				frm.trigger("validate");
				frm.refresh_fields();
			}
		});
	}
	else{
		for(let i=0; i<checked_values.length; i++){
			var si_item = frappe.model.add_child(frm.doc, 'Sales Invoice Item', 'items');
			frappe.model.set_value(si_item.doctype, si_item.name, 'item_code', checked_values[i]['item']);
			frappe.model.set_value(si_item.doctype, si_item.name, 'qty', 1);
			if(checked_values[i]['qty'] > 1){
				frappe.model.set_value(si_item.doctype, si_item.name, 'qty', parseFloat(checked_values[i]['qty']));
			}
		}
		frm.refresh_fields();
	}
};
