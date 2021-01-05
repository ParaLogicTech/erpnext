// Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.provide("erpnext.selling");

erpnext.selling.VehicleBookingOrder = frappe.ui.form.Controller.extend({
	setup: function () {
		this.frm.custom_make_buttons = {
			'Delivery Note': 'Deliver Vehicle',
			'Sales Invoice': 'Deliver Invoice',
			'Purchase Order': 'Purchase Order',
			'Purchase Invoice': 'Receive Invoice',
			'Purchase Receipt': 'Receive Vehicle',
		}
	},

	refresh: function () {
		erpnext.toggle_naming_series();
		erpnext.hide_company();
		this.set_customer_is_company_label();
		this.set_dynamic_link();
		this.setup_vehicle_route_options();
		this.setup_allocation_route_options();
		this.add_create_buttons();
	},

	onload: function () {
		this.setup_queries();
	},

	setup_queries: function () {
		var me = this;

		this.frm.set_query('customer', erpnext.queries.customer);
		this.frm.set_query('contact_person', erpnext.queries.contact_query);
		this.frm.set_query('customer_address', erpnext.queries.address_query);

		this.frm.set_query("item_code", function() {
			return erpnext.queries.item({"is_vehicle": 1, "include_in_vehicle_booking": 1});
		});

		this.frm.set_query("payment_terms_template", function() {
			return {filters: {"include_in_vehicle_booking": 1}};
		});

		this.frm.set_query("vehicle", function() {
			return {filters: {"item_code": me.frm.doc.item_code}};
		});

		this.frm.set_query("selling_transaction_type", function() {
			return {filters: {"selling": 1}};
		});
		this.frm.set_query("buying_transaction_type", function() {
			return {filters: {"buying": 1}};
		});

		this.frm.set_query("allocation_period", function () {
			var filters = {
				item_code: me.frm.doc.item_code,
				supplier: me.frm.doc.supplier
			}
			if (me.frm.doc.delivery_period) {
				filters['delivery_period'] = me.frm.doc.delivery_period;
			}
			return erpnext.queries.vehicle_allocation_period('allocation_period', filters);
		});
		this.frm.set_query("delivery_period", function () {
			if (me.frm.doc.vehicle_allocation_required) {
				var filters = {
					item_code: me.frm.doc.item_code,
					supplier: me.frm.doc.supplier
				}

				if (me.frm.doc.transaction_date) {
					filters['transaction_date'] = me.frm.doc.transaction_date;
				}
				if (me.frm.doc.allocation_period) {
					filters['allocation_period'] = me.frm.doc.allocation_period;
				}
				return erpnext.queries.vehicle_allocation_period('delivery_period', filters);
			} else if (me.frm.doc.transaction_date) {
				return {
					filters: {to_date: [">=", me.frm.doc.transaction_date]}
				}
			}
		});

		this.frm.set_query("vehicle_allocation", function() {
			var filters = {
				item_code: me.frm.doc.item_code,
				supplier: me.frm.doc.supplier,
				is_booked: 0
			}
			if (me.frm.doc.allocation_period) {
				filters['allocation_period'] = me.frm.doc.allocation_period;
			}
			if (me.frm.doc.delivery_period) {
				filters['delivery_period'] = me.frm.doc.delivery_period;
			}
			return {filters: filters};
		});
	},

	setup_vehicle_route_options: function() {
		var me = this;

		var vehicle_field = me.frm.get_docfield("vehicle");

		vehicle_field.get_route_options_for_new_doc = function() {
			return {
				"item_code": me.frm.doc.item_code,
				"item_name": me.frm.doc.item_name
			}
		}
	},

	setup_allocation_route_options: function() {
		var me = this;

		var allocation_field = me.frm.get_docfield("vehicle_allocation");

		allocation_field.get_route_options_for_new_doc = function() {
			return {
				"company": me.frm.doc.company,
				"item_code": me.frm.doc.item_code,
				"item_name": me.frm.doc.item_name,
				"supplier": me.frm.doc.supplier,
				"allocation_period": me.frm.doc.allocation_period,
				"delivery_period": me.frm.doc.delivery_period
			}
		}
	},

	add_create_buttons: function () {
		if (this.frm.doc.docstatus === 1) {
			var unpaid = flt(this.frm.doc.customer_outstanding) > 0 || flt(this.frm.doc.supplier_outstanding) > 0;

			if (flt(this.frm.doc.customer_outstanding) > 0) {
				this.frm.add_custom_button(__('Customer Payment'), () => this.make_payment_entry('Customer'), __('Payment'));
			}
			if (flt(this.frm.doc.supplier_outstanding) > 0) {
				this.frm.add_custom_button(__('Supplier Payment'), () => this.make_payment_entry('Supplier'), __('Payment'));
			}

			if (this.frm.doc.delivery_status === "To Receive") {
				this.frm.add_custom_button(__('Receive Vehicle'), () => this.make_next_document('Purchase Receipt'));
			} else if (this.frm.doc.delivery_status === "To Deliver") {
				this.frm.add_custom_button(__('Deliver Vehicle'), () => this.make_next_document('Delivery Note'));
			}

			if (this.frm.doc.delivery_status !== "To Receive") {
				if (this.frm.doc.invoice_status === "To Receive") {
					this.frm.add_custom_button(__('Receive Invoice'), () => this.make_next_document('Purchase Invoice'));
				} else if (this.frm.doc.invoice_status === "To Deliver" && this.frm.doc.delivery_status === "Delivered") {
					this.frm.add_custom_button(__('Deliver Invoice'), () => this.make_next_document('Sales Invoice'));
				}
			}

			if (unpaid) {
				this.frm.page.set_inner_btn_group_as_primary(__('Payment'));
			} else if (this.frm.doc.status === "To Receive Vehicle") {
				this.frm.custom_buttons[__('Receive Vehicle')] && this.frm.custom_buttons[__('Receive Vehicle')].addClass('btn-primary');
			} else if (this.frm.doc.status === "To Receive Invoice") {
				this.frm.custom_buttons[__('Receive Invoice')] && this.frm.custom_buttons[__('Receive Invoice')].addClass('btn-primary');
			} else if (this.frm.doc.status === "To Deliver Vehicle") {
				this.frm.custom_buttons[__('Deliver Vehicle')] && this.frm.custom_buttons[__('Deliver Vehicle')].addClass('btn-primary');
			} else if (this.frm.doc.status === "To Deliver Invoice") {
				this.frm.custom_buttons[__('Deliver Invoice')] && this.frm.custom_buttons[__('Deliver Invoice')].addClass('btn-primary');
			}
		}
	},

	company: function () {
		this.set_customer_is_company_label();
		if (this.frm.doc.company_is_customer) {
			this.get_customer_details();
		}
	},

	customer: function () {
		this.get_customer_details();
	},

	customer_is_company: function () {
		if (this.frm.doc.customer_is_company) {
			this.frm.doc.customer = "";
			this.frm.refresh_field('customer');
			this.frm.set_value("customer_name", this.frm.doc.company);
		} else {
			this.frm.set_value("customer_name", "");
		}

		this.get_customer_details();
		this.set_dynamic_link();
	},

	item_code: function () {
		var me = this;

		if (me.frm.doc.company && me.frm.doc.item_code) {
			me.frm.call({
				method: "erpnext.selling.doctype.vehicle_booking_order.vehicle_booking_order.get_item_details",
				child: me.frm.doc,
				args: {
					args: {
						company: me.frm.doc.company,
						item_code: me.frm.doc.item_code,
						customer: me.frm.doc.customer,
						supplier: me.frm.doc.supplier,
						tranasction_date: me.frm.doc.transaction_date,
						selling_transaction_type: me.frm.doc.selling_transaction_type,
						buying_transaction_type: me.frm.doc.buying_transaction_type,
						vehicle_price_list: me.frm.doc.vehicle_price_list
					}
				},
				callback: function (r) {
					if (!r.exc) {
						me.frm.set_value("vehicle_allocation", null);
						me.frm.trigger('vehicle_amount');
					}
				}
			});
		}
	},

	vehicle_allocation_required: function () {
		if (!this.frm.doc.vehicle_allocation_required) {
			this.frm.set_value("vehicle_allocation", null);
			this.frm.set_value("allocation_period", null);
		}
	},

	vehicle_amount: function () {
		this.calculate_taxes_and_totals();
	},

	withholding_tax_amount: function () {
		this.calculate_taxes_and_totals();
	},

	fni_amount: function () {
		this.calculate_taxes_and_totals();
	},

	get_customer_details: function () {
		var me = this;

		if (me.frm.doc.company && (me.frm.doc.customer || me.frm.doc.company_is_customer)) {
			frappe.call({
				method: "erpnext.selling.doctype.vehicle_booking_order.vehicle_booking_order.get_customer_details",
				args: {
					args: {
						company: me.frm.doc.company,
						customer: me.frm.doc.customer,
						company_is_customer: me.frm.doc.company_is_customer,
						item_code: me.frm.doc.item_code,
						transaction_date: me.frm.doc.transaction_date
					}
				},
				callback: function (r) {
					if (r.message && !r.exc) {
						me.frm.set_value(r.message);
					}
				}
			});
		}
	},

	set_customer_is_company_label: function() {
		if (this.frm.doc.company) {
			this.frm.fields_dict.customer_is_company.set_label(__("Customer is {0}", [this.frm.doc.company]));
		}
	},

	set_dynamic_link: function () {
		frappe.dynamic_link = {
			doc: this.frm.doc,
			fieldname: this.frm.doc.customer_is_company ? 'company' : 'customer',
			doctype: this.frm.doc.customer_is_company ? 'Company' : 'Customer'
		};
	},

	customer_address: function() {
		erpnext.utils.get_address_display(this.frm, 'customer_address', 'address_display');
	},

	contact_person: function() {
		erpnext.utils.get_contact_details(this.frm);
	},

	calculate_taxes_and_totals: function () {
		frappe.model.round_floats_in(this.frm.doc, ['vehicle_amount', 'fni_amount', 'withholding_tax_amount']);

		this.frm.doc.invoice_total = flt(this.frm.doc.vehicle_amount + this.frm.doc.fni_amount + this.frm.doc.withholding_tax_amount,
			precision('invoice_total'));

		if (this.frm.doc.docstatus === 0) {
			this.frm.doc.customer_advance = 0;
			this.frm.doc.supplier_advance = 0;
			this.frm.doc.customer_outstanding = this.frm.doc.invoice_total;
			this.frm.doc.supplier_outstanding = this.frm.doc.invoice_total;
		}

		this.frm.doc.in_words = "";

		this.frm.refresh_fields();
	},

	transaction_date: function () {
		this.frm.trigger('payment_terms_template');
	},

	delivery_date: function () {
		this.frm.trigger('payment_terms_template');
	},

	vehicle_allocation: function () {
		var me = this;
		if (me.frm.doc.vehicle_allocation) {
			frappe.call({
				method: "erpnext.selling.doctype.vehicle_allocation.vehicle_allocation.get_allocation_details",
				args: {
					vehicle_allocation: this.frm.doc.vehicle_allocation,
				},
				callback: function (r) {
					if (r.message && !r.exc) {
						$.each(['delivery_period', 'allocation_period'], function (i, fn) {
							if (r.message[fn]) {
								me.frm.doc[fn] = r.message[fn];
								me.frm.refresh_field(fn);
								delete r.message[fn];
							}
						});

						me.frm.set_value(r.message);
					}
				}
			});
		} else {
			me.frm.set_value("allocation_title", "");
		}
	},

	delivery_period: function () {
		var me = this;

		if (me.frm.doc.delivery_period) {
			me.frm.set_value("vehicle_allocation", null);

			frappe.db.get_value("Vehicle Allocation Period", me.frm.doc.delivery_period, "to_date", function (r) {
				if (r) {
					me.frm.set_value("delivery_date", r.to_date);
				}
			});
		}
	},

	allocation_period: function () {
		var me = this;

		if (me.frm.doc.allocation_period) {
			me.frm.set_value("vehicle_allocation", null);
		}
	},

	payment_terms_template: function() {
		var me = this;
		const doc = this.frm.doc;
		if(doc.payment_terms_template) {
			frappe.call({
				method: "erpnext.controllers.accounts_controller.get_payment_terms",
				args: {
					terms_template: doc.payment_terms_template,
					posting_date: doc.transaction_date,
					delivery_date: doc.delivery_date,
					grand_total: doc.invoice_total,
				},
				callback: function(r) {
					if(r.message && !r.exc) {
						me.frm.set_value("payment_schedule", r.message);
					}
				}
			})
		}
	},

	payment_term: function(doc, cdt, cdn) {
		var row = locals[cdt][cdn];
		if(row.payment_term) {
			frappe.call({
				method: "erpnext.controllers.accounts_controller.get_payment_term_details",
				args: {
					term: row.payment_term,
					posting_date: this.frm.doc.transaction_date,
					delivery_date: this.frm.doc.delivery_date,
					grand_total: this.frm.doc.invoice_total
				},
				callback: function(r) {
					if(r.message && !r.exc) {
						for (var d in r.message) {
							frappe.model.set_value(cdt, cdn, d, r.message[d]);
						}
					}
				}
			})
		}
	},

	make_payment_entry: function(party_type) {
		if (['Customer', 'Supplier'].includes(party_type)) {
			return frappe.call({
				method: "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
				args: {
					"dt": this.frm.doc.doctype,
					"dn": this.frm.doc.name,
					"party_type": party_type,
					"mode_of_payment": party_type === "Customer" ? this.frm.doc.selling_mode_of_payment : this.frm.doc.buying_mode_of_payment
				},
				callback: function (r) {
					var doclist = frappe.model.sync(r.message);
					frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				}
			});
		}
	},

	make_next_document: function(doctype) {
		if (!doctype)
			return;

		return frappe.call({
			method: "erpnext.selling.doctype.vehicle_booking_order.vehicle_booking_order.get_next_document",
			args: {
				"vehicle_booking_order": this.frm.doc.name,
				"doctype": doctype
			},
			callback: function (r) {
				if (!r.exc) {
					var doclist = frappe.model.sync(r.message);
					frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				}
			}
		});
	},
});

$.extend(cur_frm.cscript, new erpnext.selling.VehicleBookingOrder({frm: cur_frm}));
