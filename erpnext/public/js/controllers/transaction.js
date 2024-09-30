// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

erpnext.update_item_args_for_pricing_hooks = [];

erpnext.TransactionController = class TransactionController extends erpnext.taxes_and_totals {
	setup() {
		frappe.flags.hide_serial_batch_dialog = true
		super.setup();

		erpnext.setup_applies_to_fields(this.frm);

		frappe.ui.form.on(this.frm.doctype + " Item", "rate", function(frm, cdt, cdn) {
			let item = frappe.get_doc(cdt, cdn);
			frm.cscript.set_item_rate(item);
			frm.cscript.calculate_taxes_and_totals();
		});

		frappe.ui.form.on(this.frm.doctype + " Item", "alt_uom_rate", function(frm, cdt, cdn) {
			let item = frappe.get_doc(cdt, cdn);
			frappe.model.set_value(cdt, cdn, "rate", flt(item.alt_uom_rate) * flt(item.alt_uom_size || 1));
		});

		frappe.ui.form.on(this.frm.doctype + " Item", "amount", function(frm, cdt, cdn) {
			var item = frappe.get_doc(cdt, cdn);

			item.amount = flt(item.amount, precision('amount', item));
			if (flt(item.qty)) {
				frappe.model.set_value(cdt, cdn, 'rate', item.amount / flt(item.qty));
			} else {
				frappe.model.set_value(cdt, cdn, 'rate', item.amount);
			}
		});

		frappe.ui.form.on(this.frm.doctype + " Item", "amount_before_discount", function(frm, cdt, cdn) {
			var item = frappe.get_doc(cdt, cdn);
			var margin_df = frappe.meta.get_docfield(cdt, 'margin_type');

			if (margin_df) {
				item.margin_rate_or_amount = 0;
			}

			item.amount_before_discount = flt(item.amount_before_discount, precision('amount_before_discount', item));
			if (flt(item.qty)) {
				item.price_list_rate = item.amount_before_discount / flt(item.qty);
			} else {
				item.price_list_rate = item.amount_before_discount;
			}

			frappe.model.trigger('price_list_rate', item.price_list_rate, item);
		});

		frappe.ui.form.on(this.frm.doctype + " Item", "total_discount", function(frm, cdt, cdn) {
			var item = frappe.get_doc(cdt, cdn);

			item.total_discount = flt(item.total_discount, precision('total_discount', item));
			if (flt(item.qty)) {
				frappe.model.set_value(cdt, cdn, 'discount_amount', item.total_discount / flt(item.qty));
			} else {
				frappe.model.set_value(cdt, cdn, 'discount_amount', item.total_discount);
			}
		});

		frappe.ui.form.on(this.frm.doctype + " Item", "tax_inclusive_amount_before_discount", function(frm, cdt, cdn) {
			var item = frappe.get_doc(cdt, cdn);

			item.tax_inclusive_amount = flt(item.tax_inclusive_amount);
			if (flt(item.qty)) {
				frappe.model.set_value(cdt, cdn, 'tax_inclusive_rate_before_discount',
					item.tax_inclusive_amount_before_discount / flt(item.qty));
			} else {
				frappe.model.set_value(cdt, cdn, 'tax_inclusive_rate_before_discount',
					item.tax_inclusive_amount_before_discount);
			}
		});

		frappe.ui.form.on(this.frm.doctype + " Item", "tax_inclusive_rate_before_discount", function(frm, cdt, cdn) {
			let tax_rows = (frm.doc.taxes || []).filter(
				tax => tax.charge_type != "Actual" && !tax.exclude_from_item_tax_amount
			);

			let invalid_charge_types = tax_rows.filter(tax => tax.charge_type != 'On Net Total');
			if (invalid_charge_types.length) {
				frappe.msgprint(__('Cannot calculate Rate from Tax Inclusive Rate'));
				frm.cscript.calculate_taxes_and_totals();
				return
			}

			let item = frappe.get_doc(cdt, cdn);
			let item_tax_map = frm.cscript._load_item_tax_rate(item.item_tax_rate);

			let tax_inclusive_rate = flt(item.tax_inclusive_rate_before_discount);

			let tax_fraction = 0;
			let inclusive_tax_fraction = 0;
			$.each(tax_rows, function (i, tax) {
				let tax_rate = frm.cscript._get_tax_rate(tax, item_tax_map);

				tax_fraction += tax_rate / 100;
				if (tax.included_in_print_rate) {
					inclusive_tax_fraction += tax_rate / 100
				}
			});

			let rate;
			if (cint(item.apply_taxes_on_retail)) {
				rate = (tax_inclusive_rate - flt(item.taxable_rate) * tax_fraction) * (1 + inclusive_tax_fraction);
			} else {
				rate = tax_inclusive_rate / (1 + tax_fraction) * (1 + inclusive_tax_fraction);
			}

			frappe.model.set_value(cdt, cdn, 'rate', rate);
		});

		frappe.ui.form.on(this.frm.cscript.tax_table, "rate", function(frm, cdt, cdn) {
			cur_frm.cscript.calculate_taxes_and_totals();
		});

		frappe.ui.form.on(this.frm.cscript.tax_table, "tax_amount", function(frm, cdt, cdn) {
			cur_frm.cscript.calculate_taxes_and_totals();
		});

		frappe.ui.form.on(this.frm.cscript.tax_table, "base_tax_amount", function(frm, cdt, cdn) {
			if (flt(frm.doc.conversion_rate)>0.0) {
				var tax = locals[cdt][cdn];
				tax.tax_amount = flt(tax.base_tax_amount) / flt(frm.doc.conversion_rate);
				cur_frm.cscript.calculate_taxes_and_totals();
			}
		});

		frappe.ui.form.on(this.frm.cscript.tax_table, "row_id", function(frm, cdt, cdn) {
			cur_frm.cscript.calculate_taxes_and_totals();
		});

		frappe.ui.form.on(this.frm.cscript.tax_table, "included_in_print_rate", function(frm, cdt, cdn) {
			cur_frm.cscript.set_dynamic_labels();
			cur_frm.cscript.calculate_taxes_and_totals();
		});

		frappe.ui.form.on(this.frm.cscript.tax_table, "apply_on_net_amount", function(frm, cdt, cdn) {
			cur_frm.cscript.calculate_taxes_and_totals();
		});

		frappe.ui.form.on(this.frm.cscript.tax_table, {
			taxes_remove: function(frm, cdt, cdn) {
				cur_frm.cscript.set_dynamic_labels();
				cur_frm.cscript.calculate_taxes_and_totals();
			}
		});

		frappe.ui.form.on(this.frm.doctype, "calculate_tax_on_company_currency", function(frm, cdt, cdn) {
			cur_frm.cscript.calculate_taxes_and_totals();
		});

		frappe.ui.form.on(this.frm.doctype, "apply_discount_on", function(frm) {
			if(frm.doc.additional_discount_percentage) {
				frm.trigger("additional_discount_percentage");
			} else {
				cur_frm.cscript.calculate_taxes_and_totals();
			}
		});

		frappe.ui.form.on(this.frm.doctype, "additional_discount_percentage", function(frm) {
			if(!frm.doc.apply_discount_on) {
				frappe.msgprint(__("Please set 'Apply Additional Discount On'"));
				return;
			}

			frm.via_discount_percentage = true;

			if(frm.doc.additional_discount_percentage && frm.doc.discount_amount) {
				// Reset discount amount and net / grand total
				frm.doc.discount_amount = 0;
				frm.cscript.calculate_taxes_and_totals();
			}

			var total = flt(frm.doc[frappe.model.scrub(frm.doc.apply_discount_on)]);
			var discount_amount = flt(total*flt(frm.doc.additional_discount_percentage) / 100,
				precision("discount_amount"));

			frm.set_value("discount_amount", discount_amount)
				.then(() => delete frm.via_discount_percentage);
		});

		frappe.ui.form.on(this.frm.doctype, "discount_amount", function(frm) {
			frm.cscript.set_dynamic_labels();

			if (!frm.via_discount_percentage) {
				frm.doc.additional_discount_percentage = 0;
			}

			frm.cscript.calculate_taxes_and_totals();
		});

		frappe.ui.form.on(this.frm.doctype + " Item", {
			items_add: function(frm, cdt, cdn) {
				var item = frappe.get_doc(cdt, cdn);
				if(!item.warehouse && frm.doc.set_warehouse) {
					item.warehouse = frm.doc.set_warehouse;
				}
			},

			items_remove: function (frm) {
				frm.cscript.calculate_taxes_and_totals();
			},

			project: function(frm, cdt, cdn) {
				let row = frappe.get_doc(cdt, cdn);
				return frm.cscript.update_item_defaults(false, row);
			}
		});

		frappe.ui.form.on(this.frm.doctype, "project", function(frm) {
			if (frm.doc.claim_billing && frm.doc.project) {
				frm.doc.project = null;
				frm.refresh_field('project');
			}

			if (frm.doc.doctype == "Sales Invoice" && !frm.doc.claim_billing) {
				frm.cscript.copy_project_in_items();
			}

			if (frm.doc.project) {
				return frappe.run_serially([
					() => frm.cscript.get_project_details(),
					() => frm.cscript.update_item_defaults(false),
				]);
			} else {
				if (frm.fields_dict.project_reference_no) {
					frm.set_value("project_reference_no", null);
				}

				frm.cscript.update_item_defaults(false);
				frm.events.get_applies_to_details(frm);
			}
		});

		var me = this;
		if(this.frm.fields_dict["items"].grid.get_field('batch_no')) {
			this.frm.set_query("batch_no", "items", function(doc, cdt, cdn) {
				return me.set_query_for_batch(doc, cdt, cdn);
			});
		}

		if(
			this.frm.docstatus < 2
			&& this.frm.fields_dict["payment_terms_template"]
			&& this.frm.fields_dict["payment_schedule"]
			&& this.frm.doc.payment_terms_template
			&& !this.frm.doc.payment_schedule.length
		){
			this.frm.trigger("payment_terms_template");
		}

		if(this.frm.fields_dict["recurring_print_format"]) {
			this.frm.set_query("recurring_print_format", function(doc) {
				return{
					filters: [
						['Print Format', 'doc_type', '=', cur_frm.doctype],
					]
				};
			});
		}

		this.frm.set_query("uom", "items", function(doc, cdt, cdn) {
			let item = frappe.get_doc(cdt, cdn);
			return erpnext.queries.item_uom(item.item_code);
		});

		if(this.frm.fields_dict["return_against"]) {
			this.frm.set_query("return_against", function(doc) {
				var filters = {
					"docstatus": 1,
					"is_return": 0,
					"company": doc.company
				};
				if (me.frm.fields_dict["customer"] && doc.customer) filters["customer"] = doc.customer;
				if (me.frm.fields_dict["supplier"] && doc.supplier) filters["supplier"] = doc.supplier;

				return {
					filters: filters
				};
			});
		}
		if (this.frm.fields_dict["items"].grid.get_field("cost_center")) {
			this.frm.set_query("cost_center", "items", function(doc) {
				return {
					filters: {
						"company": doc.company,
						"is_group": 0
					}
				};
			});
		}

		if (this.frm.fields_dict["cost_center"]) {
			this.frm.set_query("cost_center", function(doc) {
				return {
					filters: {
						"company": doc.company,
						"is_group": 0
					}
				};
			});
		}

		if (this.frm.fields_dict["items"].grid.get_field("expense_account")) {
			this.frm.set_query("expense_account", "items", function(doc) {
				return {
					filters: {
						"company": doc.company,
						"is_group": 0
					}
				};
			});
		}

		let batch_no_field = this.frm.get_docfield("items", "batch_no");
		if (batch_no_field) {
			batch_no_field.get_route_options_for_new_doc = function(row) {
				return {
					"item": row.doc.item_code
				}
			};
		}

		if (this.frm.fields_dict["items"].grid.get_field('blanket_order')) {
			this.frm.set_query("blanket_order", "items", function(doc, cdt, cdn) {
				var item = locals[cdt][cdn];
				return {
					query: "erpnext.controllers.queries.get_blanket_orders",
					filters: {
						"company": doc.company,
						"blanket_order_type": doc.doctype === "Sales Order" ? "Selling" : "Purchasing",
						"item": item.item_code
					}
				}
			});
		}

		var vehicle_field = me.frm.get_docfield("applies_to_vehicle");
		if (vehicle_field) {
			vehicle_field.get_route_options_for_new_doc = function () {
				return {
					"item_code": me.frm.doc.applies_to_item,
					"item_name": me.frm.doc.applies_to_item_name,
					"unregistered": me.frm.doc.vehicle_unregistered,
					"license_plate": me.frm.doc.vehicle_license_plate,
					"chassis_no": me.frm.doc.vehicle_chassis_no,
					"engine_no": me.frm.doc.vehicle_engine_no,
					"color": me.frm.doc.vehicle_color,
				}
			}
		}

		if(this.frm.fields_dict.taxes_and_charges) {
			this.frm.set_query("taxes_and_charges", function() {
				return {
					filters: {
						'company': me.frm.doc.company,
					}
				}
			});
		}

		if (this.frm.doc.__onload && this.frm.doc.__onload.enable_dynamic_bundling) {
			erpnext.bundling.setup_bundling(this.frm.doc.doctype);
		}
	}
	onload() {
		var me = this;

		erpnext.utils.setup_scan_barcode_field(this.frm.fields_dict.scan_barcode);

		if(this.frm.doc.__islocal) {
			var currency = frappe.defaults.get_user_default("currency");

			let set_value = (fieldname, value) => {
				if(me.frm.fields_dict[fieldname] && !me.frm.doc[fieldname]) {
					return me.frm.set_value(fieldname, value);
				}
			};

			return frappe.run_serially([
				() => set_value('currency', currency),
				() => set_value('price_list_currency', currency),
				() => set_value('status', 'Draft'),
				() => {
					if(this.frm.doc.company && !this.frm.doc.amended_from) {
						this.set_company_defaults();
					}
				}
			]);
		}
	}

	is_return() {
		if(!this.frm.doc.is_return && this.frm.doc.return_against) {
			this.frm.set_value('return_against', '');
		}
	}

	setup_quality_inspection() {
		if(!in_list(["Delivery Note", "Sales Invoice", "Purchase Receipt", "Purchase Invoice"], this.frm.doc.doctype)) {
			return;
		}
		var me = this;
		var inspection_type = in_list(["Purchase Receipt", "Purchase Invoice"], this.frm.doc.doctype)
			? "Incoming" : "Outgoing";

		var quality_inspection_field = this.frm.get_docfield("items", "quality_inspection");
		quality_inspection_field.get_route_options_for_new_doc = function(row) {
			if(me.frm.is_new()) return;
			return {
				"inspection_type": inspection_type,
				"reference_type": me.frm.doc.doctype,
				"reference_name": me.frm.doc.name,
				"item_code": row.doc.item_code,
				"description": row.doc.description,
				"item_serial_no": row.doc.serial_no ? row.doc.serial_no.split("\n")[0] : null,
				"batch_no": row.doc.batch_no,
				"project": inspection_type == "Incoming" ? row.doc.project : me.frm.doc.project
			}
		}

		this.frm.set_query("quality_inspection", "items", function(doc, cdt, cdn) {
			var d = locals[cdt][cdn];
			return {
				filters: {
					docstatus: 1,
					inspection_type: inspection_type,
					reference_name: doc.name,
					item_code: d.item_code
				}
			}
		});
	}

	make_payment_request() {
		var me = this;
		const payment_request_type = (in_list(['Sales Order', 'Sales Invoice'], this.frm.doc.doctype))
			? "Inward" : "Outward";

		frappe.call({
			method:"erpnext.accounts.doctype.payment_request.payment_request.make_payment_request",
			args: {
				dt: me.frm.doc.doctype,
				dn: me.frm.doc.name,
				recipient_id: me.frm.doc.contact_email,
				payment_request_type: payment_request_type,
				party_type: payment_request_type == 'Outward' ? "Supplier" : "Customer",
				party: payment_request_type == 'Outward' ? me.frm.doc.supplier : me.frm.doc.customer
			},
			callback: function(r) {
				if(!r.exc){
					var doc = frappe.model.sync(r.message);
					frappe.set_route("Form", r.message.doctype, r.message.name);
				}
			}
		})
	}

	onload_post_render() {
		if(this.frm.doc.__islocal && !(this.frm.doc.taxes || []).length
			&& !(this.frm.doc.__onload ? this.frm.doc.__onload.load_after_mapping : false)) {
			frappe.after_ajax(() => this.apply_default_taxes());
		} else if(this.frm.doc.__islocal && this.frm.doc.company && this.frm.doc["items"]
			&& !this.frm.doc.is_pos) {
			frappe.after_ajax(() => this.calculate_taxes_and_totals());
		}
		if(frappe.meta.get_docfield(this.frm.doc.doctype + " Item", "item_code")) {
			this.setup_item_selector();
			this.frm.get_field("items").grid.set_multiple_add("item_code", "qty");
		}
	}

	refresh() {
		erpnext.toggle_naming_series();
		erpnext.hide_company();
		this.set_dynamic_labels();
		this.setup_sms();
		this.setup_quality_inspection();

		if (frappe.meta.get_docfield(this.frm.doc.doctype, "pricing_rules")) {
			this.frm.set_indicator_formatter('pricing_rule', function(doc) {
				return (doc.rule_applied) ? "green" : "red";
			});
		}
	}

	update_item_prices() {
		var me = this;
		var frm = this.frm;

		var rows;
		var checked_rows = frm.fields_dict.items.grid.grid_rows.filter(row => row.doc.__checked);
		if (checked_rows.length) {
			rows = checked_rows;
		} else {
			rows = frm.fields_dict.items.grid.grid_rows;
		}

		rows = rows
			.filter(row => row.doc.item_code && (row.doc.price_list_rate || row.doc.rate))
			.map(function(row) { return {
				item_code: row.doc.item_code,
				item_name: row.doc.item_name,
				price_list_rate: row.doc.price_list_rate || row.doc.rate,
				uom: row.doc.uom,
				conversion_factor: row.doc.conversion_factor
			}});

		var price_list = frm.doc.selling_price_list || frm.doc.buying_price_list;
		var date = frm.doc.transaction_date || frm.doc.posting_date;
		this.data = [];

		if (price_list && rows.length) {
			var dialog = new frappe.ui.Dialog({
				title: __("Update Price List {0}", [price_list]), fields: [
					{label: __("Effective Date"), fieldname: "effective_date", fieldtype: "Date", default: date, reqd: 1},
					{label: __("Item Prices"), fieldname: "items", fieldtype: "Table", data: this.data,
						get_data: () => this.data,
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
								label: __('UOM'),
								fieldtype:'Link',
								fieldname:"uom",
								read_only: 1,
								in_list_view: 1,
								columns: 2,
							},
							{
								label: __('New Rate'),
								fieldtype:'Currency',
								fieldname:"price_list_rate",
								default: 0,
								read_only: 1,
								in_list_view: 1,
								columns: 2,
							},
							{
								label: __('Conversion Factor'),
								fieldtype:'Float',
								precision: 9,
								fieldname:"conversion_factor",
								read_only: 1
							}
						]
					}
				]
			});

			dialog.fields_dict.items.df.data = rows;
			this.data = dialog.fields_dict.items.df.data;
			dialog.fields_dict.items.grid.refresh();

			dialog.show();
			dialog.set_primary_action(__('Update Price List'), function() {
				var updated_items = this.get_values()["items"];
				return frappe.call({
					method: "erpnext.stock.report.item_prices.item_prices.set_multiple_item_pl_rate",
					args: {
						effective_date: dialog.get_value('effective_date'),
						items: updated_items,
						price_list: price_list
					},
					callback: function() {
						dialog.hide();
					}
				});
			});
		}
	}

	scan_barcode() {
		const barcode_scanner = new erpnext.utils.BarcodeScanner({frm:this.frm});
		barcode_scanner.process_scan();
	}

	apply_default_taxes() {
		var me = this;
		var taxes_and_charges_field = frappe.meta.get_docfield(me.frm.doc.doctype, "taxes_and_charges",
			me.frm.doc.name);

		if (!this.frm.doc.taxes_and_charges && this.frm.doc.taxes) {
			return;
		}

		if (taxes_and_charges_field) {
			return frappe.call({
				method: "erpnext.controllers.transaction_controller.get_default_taxes_and_charges",
				args: {
					"master_doctype": taxes_and_charges_field.options,
					"tax_template": me.frm.doc.taxes_and_charges,
					"company": me.frm.doc.company
				},
				callback: function(r) {
					if(!r.exc && r.message) {
						frappe.run_serially([
							() => {
								// directly set in doc, so as not to call triggers
								if(r.message.taxes_and_charges) {
									me.frm.doc.taxes_and_charges = r.message.taxes_and_charges;
								}

								// set taxes table
								if(r.message.taxes) {
									me.frm.set_value("taxes", r.message.taxes);
								}
							},
							() => me.set_dynamic_labels(),
							() => me.calculate_taxes_and_totals()
						]);
					}
				}
			});
		}
	}

	setup_sms() {
		var me = this;
		let blacklist_dt = ['Purchase Invoice', 'BOM'];
		let blacklist_status = in_list(["Lost", "Stopped", "Closed"], this.frm.doc.status);

		if(this.frm.doc.docstatus===1 && !blacklist_status && !blacklist_dt.includes(this.frm.doctype)) {
			this.frm.page.add_menu_item(__('Send SMS'), function() {
				me.send_sms();
			});
		}
	}

	send_sms() {
		var doc = this.frm.doc;
		var args = {};

		args.contact = doc.contact_person || doc.customer_primary_contact;
		args.mobile_no = doc.contact_mobile || doc.mobile_no || doc.contact_no;

		if (in_list(['Sales Order', 'Delivery Note', 'Sales Invoice'], doc.doctype)) {
			args.party_doctype = 'Customer';
			args.party = doc.bill_to || doc.customer;

		} else if (doc.doctype == 'Quotation') {
			args.party_doctype = doc.quotation_to;
			args.party = doc.party_name;

		} else if (in_list(['Purchase Order', 'Purchase Receipt'], doc.doctype)) {
			args.party_doctype = 'Supplier';
			args.party = doc.supplier;

		} else if (in_list(['Lead', 'Customer', 'Supplier'], doc.doctype)) {
			args.party_doctype = doc.doctype;
			args.party = doc.name;
		}

		new frappe.SMSManager(doc, args);
	}

	barcode(doc, cdt, cdn) {
		var d = locals[cdt][cdn];
		if(d.barcode=="" || d.barcode==null) {
			// barcode cleared, remove item
			d.item_code = "";
		}

		this.frm.from_barcode = true;
		this.item_code(doc, cdt, cdn);
	}

	item_code(doc, cdt, cdn) {
		var me = this;
		var item = frappe.get_doc(cdt, cdn);

		var update_stock = 0;
		if(['Sales Invoice'].includes(me.frm.doc.doctype)) {
			update_stock = cint(me.frm.doc.update_stock);
		}

		// clear barcode if setting item (else barcode will take priority)
		if(!me.frm.from_barcode) {
			item.barcode = null;
		}

		me.frm.from_barcode = false;
		if(item.item_code || item.barcode || item.serial_no || item.vehicle) {
			if(!me.validate_company_and_party()) {
				me.frm.fields_dict["items"].grid.grid_rows[item.idx - 1].remove();
			} else {
				return me.frm.call({
					method: "erpnext.stock.get_item_details.get_item_details",
					child: item,
					args: {
						doc: me.frm.doc,
						args: {
							item_code: item.item_code,
							hide_item_code: item.hide_item_code,
							barcode: item.barcode,
							serial_no: item.serial_no,
							vehicle: item.vehicle,
							batch_no: item.batch_no,
							set_warehouse: me.frm.doc.set_warehouse,
							default_depreciation_percentage: me.frm.doc.default_depreciation_percentage,
							default_underinsurance_percentage: me.frm.doc.default_underinsurance_percentage,
							warehouse: item.warehouse,
							customer: me.frm.doc.customer || me.frm.doc.party_name,
							bill_to: me.frm.doc.bill_to,
							quotation_to: me.frm.doc.quotation_to,
							supplier: me.frm.doc.supplier,
							currency: me.frm.doc.currency,
							update_stock: update_stock,
							conversion_rate: me.frm.doc.conversion_rate,
							retail_price_list: me.frm.doc.retail_price_list,
							price_list: me.frm.doc.selling_price_list || me.frm.doc.buying_price_list,
							price_list_currency: me.frm.doc.price_list_currency,
							plc_conversion_rate: me.frm.doc.plc_conversion_rate,
							company: me.frm.doc.company,
							order_type: me.frm.doc.order_type,
							transaction_type_name: me.frm.doc.transaction_type,
							is_pos: cint(me.frm.doc.is_pos),
							is_subcontracted: me.frm.doc.is_subcontracted,
							transaction_date: me.frm.doc.transaction_date || me.frm.doc.posting_date,
							ignore_pricing_rule: me.frm.doc.ignore_pricing_rule,
							doctype: me.frm.doc.doctype,
							name: me.frm.doc.name,
							project: item.project || me.frm.doc.project,
							campaign: me.frm.doc.campaign,
							qty: item.qty || 1,
							stock_qty: item.stock_qty,
							manufacturer: item.manufacturer,
							stock_uom: item.stock_uom,
							pos_profile: me.frm.doc.doctype == 'Sales Invoice' ? me.frm.doc.pos_profile : '',
							cost_center: item.cost_center,
							apply_taxes_on_retail: item.apply_taxes_on_retail,
							allow_zero_valuation_rate: item.allow_zero_valuation_rate,
							tax_category: me.frm.doc.tax_category,
							child_docname: item.name,
						}
					},

					callback: function(r) {
						if(!r.exc) {
							frappe.run_serially([
								() => {
									var d = locals[cdt][cdn];
									me.add_taxes_from_item_tax_template(d.item_tax_rate);
									if (d.free_item_data) {
										me.apply_product_discount(d.free_item_data);
									}
								},
								() => me.frm.script_manager.trigger("price_list_rate", cdt, cdn),
								() => me.conversion_factor(doc, cdt, cdn, true),
								() => me.show_hide_select_batch_button && me.show_hide_select_batch_button(),
								() => me.set_skip_delivery_note && me.set_skip_delivery_note(),
								() => me.remove_pricing_rule(item),
								() => {
									if (item.apply_rule_on_other_items) {
										let key = item.name;
										me.apply_rule_on_other_items({key: item});
									}
								}
							]);
						}
					}
				});
			}
		}
	}

	get_project_details() {
		var me = this;

		if (me.frm.doc.project) {
			return frappe.call({
				method: 'erpnext.projects.doctype.project.project.get_project_details',
				args: {
					project: me.frm.doc.project,
					doctype: me.frm.doc.doctype
				},
				callback: function (r) {
					if (!r.exc) {
						var customer = null;
						var bill_to = null;
						var applies_to_vehicle = null;

						// Set Customer and Bill To first
						if (r.message.customer) {
							customer = r.message.customer;
							delete r.message['customer'];
						}
						if (r.message.bill_to) {
							bill_to = r.message.bill_to;
							delete r.message['bill_to'];
						}

						// Set Applies to Vehicle Later
						if (r.message.applies_to_vehicle) {
							applies_to_vehicle = r.message['applies_to_vehicle'];
							delete r.message['applies_to_vehicle'];
							delete r.message['applies_to_item'];
							// Remove Applies to Vehicle if Applies to Item is given
						} else if (r.message.applies_to_item && me.frm.fields_dict.applies_to_vehicle) {
							me.frm.doc.applies_to_vehicle = null;
							me.frm.refresh_field('applies_to_vehicle');
						}

						return frappe.run_serially([
							() => {
								if (bill_to && me.frm.fields_dict.bill_to) {
									me.frm.doc.customer = customer;
									return me.frm.set_value('bill_to', bill_to);
								} else if (customer && me.frm.fields_dict.customer) {
									return me.frm.set_value('customer', customer);
								}
							},
							() => me.frm.set_value(r.message),
							() => {
								if (applies_to_vehicle && me.frm.fields_dict.applies_to_vehicle) {
									return me.frm.set_value("applies_to_vehicle", applies_to_vehicle);
								}
							},
						]);
					}
				}
			});
		}
	}

	add_taxes_from_item_tax_template(item_tax_map) {
		let me = this;

		if(item_tax_map && cint(frappe.defaults.get_default("add_taxes_from_item_tax_template"))) {
			if(typeof (item_tax_map) == "string") {
				item_tax_map = JSON.parse(item_tax_map);
			}

			$.each(item_tax_map, function(tax, rate) {
				let found = (me.frm.doc.taxes || []).find(d => d.account_head === tax);
				if(!found) {
					let child = frappe.model.add_child(me.frm.doc, "taxes");
					child.charge_type = "On Net Total";
					child.account_head = tax;
					child.rate = 0;
				}
			});
		}
	}

	serial_no(doc, cdt, cdn) {
		var me = this;
		var item = frappe.get_doc(cdt, cdn);

		if (item && item.serial_no) {
			if (!item.item_code) {
				this.frm.trigger("item_code", cdt, cdn);
			}
			else {
				var valid_serial_nos = [];

				// Replacing all occurences of comma with carriage return
				var serial_nos = item.serial_no.trim().replace(/,/g, '\n');

				serial_nos = serial_nos.trim().split('\n');

				// Trim each string and push unique string to new list
				for (var x=0; x<=serial_nos.length - 1; x++) {
					if (serial_nos[x].trim() != "" && valid_serial_nos.indexOf(serial_nos[x].trim()) == -1) {
						valid_serial_nos.push(serial_nos[x].trim());
					}
				}

				// Add the new list to the serial no. field in grid with each in new line
				item.serial_no = valid_serial_nos.join('\n');
				item.conversion_factor = item.conversion_factor || 1;

				refresh_field("serial_no", item.name, item.parentfield);
				if(!doc.is_return && cint(user_defaults.set_qty_in_transactions_based_on_serial_no_input)) {
					frappe.model.set_value(item.doctype, item.name,
						"qty", valid_serial_nos.length / item.conversion_factor);
					frappe.model.set_value(item.doctype, item.name, "stock_qty", valid_serial_nos.length);
				}
			}
		}
	}

	vehicle(doc, cdt, cdn) {
		var item = frappe.get_doc(cdt, cdn);

		if (item && item.vehicle && !item.item_code) {
			this.frm.trigger("item_code", cdt, cdn);
		}
	}

	apply_taxes_on_retail() {
		this.set_dynamic_labels();
		this.calculate_taxes_and_totals();
	}

	validate() {
		this.calculate_taxes_and_totals(false);
	}

	company() {
		this.set_company_defaults(true);
	}

	set_company_defaults(reset_account) {
		var me = this;
		var set_pricing = function() {
			if(me.frm.doc.company && me.frm.fields_dict.currency) {
				var company_currency = me.get_company_currency();
				var company_doc = frappe.get_doc(":Company", me.frm.doc.company);

				if (!me.frm.doc.currency) {
					me.frm.set_value("currency", company_currency);
				}

				if (me.frm.doc.currency == company_currency) {
					me.frm.set_value("conversion_rate", 1.0);
				}
				if (me.frm.doc.price_list_currency == company_currency) {
					me.frm.set_value('plc_conversion_rate', 1.0);
				}
				if (company_doc.default_letter_head) {
					if(me.frm.fields_dict.letter_head) {
						me.frm.set_value("letter_head", company_doc.default_letter_head);
					}
				}
				let selling_doctypes_for_tc = ["Sales Invoice", "Quotation", "Sales Order", "Delivery Note"];
				if (company_doc.default_selling_terms && frappe.meta.has_field(me.frm.doc.doctype, "tc_name") &&
				selling_doctypes_for_tc.indexOf(me.frm.doc.doctype) != -1) {
					me.frm.set_value("tc_name", company_doc.default_selling_terms);
				}
				let buying_doctypes_for_tc = ["Request for Quotation", "Supplier Quotation", "Purchase Order",
					"Material Request", "Purchase Receipt"];
				// Purchase Invoice is excluded as per issue #3345
				if (company_doc.default_buying_terms && frappe.meta.has_field(me.frm.doc.doctype, "tc_name") &&
				buying_doctypes_for_tc.indexOf(me.frm.doc.doctype) != -1) {
					me.frm.set_value("tc_name", company_doc.default_buying_terms);
				}

				frappe.run_serially([
					() => me.frm.script_manager.trigger("currency"),
					() => me.update_item_tax_map(),
					() => me.apply_default_taxes(),
					() => me.apply_pricing_rule()
				]);
			}
		}

		var set_party_account = function(set_pricing) {
			if (in_list(["Sales Invoice", "Purchase Invoice"], me.frm.doc.doctype)) {
				if(me.frm.doc.doctype=="Sales Invoice") {
					var party_type = "Customer";
					var party_account_field = 'debit_to';
				} else {
					var party_type = me.frm.doc.letter_of_credit ? "Letter of Credit" : "Supplier";
					var party_account_field = 'credit_to';
				}

				var party = me.frm.doc.bill_to || me.frm.doc[frappe.model.scrub(party_type)];
				if(party && me.frm.doc.company) {
					return frappe.call({
						method: "erpnext.accounts.party.get_party_account_details",
						args: {
							company: me.frm.doc.company,
							party_type: party_type,
							party: party,
							transaction_type: me.frm.doc.transaction_type
						},
						callback: function(r) {
							if(!r.exc && r.message) {
								if (reset_account || !me.frm.doc[party_account_field]) {
									me.frm.set_value(party_account_field, r.message.account);
								}
								if (r.message.cost_center && (reset_account || !me.frm.doc.cost_center)) {
									me.frm.set_value("cost_center", r.message.cost_center);
								}
								set_pricing();
							}
						}
					});
				} else {
					set_pricing();
				}
			} else {
				set_pricing();
			}

		}

		if (this.frm.doc.posting_date) var date = this.frm.doc.posting_date;
		else var date = this.frm.doc.transaction_date;

		if (frappe.meta.get_docfield(this.frm.doctype, "shipping_address") &&
			in_list(['Purchase Order', 'Purchase Receipt', 'Purchase Invoice'], this.frm.doctype)){
			erpnext.utils.get_shipping_address(this.frm, function(){
				set_party_account(set_pricing);
			})
		} else {
			set_party_account(set_pricing);
		}

		this.update_item_defaults(false);

		if(this.frm.doc.company) {
			erpnext.last_selected_company = this.frm.doc.company;
		}
	}

	transaction_date() {
		if (this.frm.doc.transaction_date) {
			this.frm.transaction_date = this.frm.doc.transaction_date;

			return frappe.run_serially([
				() => this.frm.trigger("currency"),
				() => erpnext.utils.set_taxes(this.frm, "posting_date"),
				() => this.update_item_tax_map(),
			]);
		}
	}

	posting_date() {
		if (this.frm.doc.posting_date) {
			this.frm.posting_date = this.frm.doc.posting_date;

			return frappe.run_serially([
				() => this.get_due_date(),
				() => this.frm.trigger("currency"),
				() => erpnext.utils.set_taxes(this.frm, "posting_date"),
				() => this.update_item_tax_map(),
			]);
		}
	}

	get_due_date() {
		let me = this;

		if (
			(this.frm.doc.doctype == "Sales Invoice" && this.frm.doc.customer)
			|| (this.frm.doc.doctype == "Purchase Invoice" && this.frm.doc.supplier)
		) {
			return frappe.call({
				method: "erpnext.accounts.party.get_due_date",
				args: {
					"posting_date": me.frm.doc.posting_date,
					"bill_date": me.frm.doc.bill_date,
					"delivery_date": me.frm.doc.delivery_date || me.frm.doc.schedule_date,
					"party_type": me.frm.doc.doctype == "Sales Invoice" ? "Customer" : "Supplier",
					"party": me.frm.doc.doctype == "Sales Invoice" ? me.frm.doc.customer : me.frm.doc.supplier,
					"payment_terms_template": me.frm.doc.payment_terms_template,
					"company": me.frm.doc.company
				},
				callback: function (r, rt) {
					if (r.message) {
						me.frm.doc.due_date = r.message;
						refresh_field("due_date");

						return me.recalculate_terms();
					}
				}
			});
		}
	}

	due_date() {
		// due_date is to be changed, payment terms template and/or payment schedule must
		// be removed as due_date is automatically changed based on payment terms
		if (this.frm.doc.due_date && !this.frm.updating_party_details && !this.frm.doc.is_pos) {
			if (this.frm.doc.payment_terms_template ||
				(this.frm.doc.payment_schedule && this.frm.doc.payment_schedule.length)) {
				var message1 = "";
				var message2 = "";
				var final_message = "Please clear the ";

				if (this.frm.doc.payment_terms_template) {
					message1 = "selected Payment Terms Template";
					final_message = final_message + message1;
				}

				if ((this.frm.doc.payment_schedule || []).length) {
					message2 = "Payment Schedule Table";
					if (message1.length !== 0) message2 = " and " + message2;
					final_message = final_message + message2;
				}
				frappe.msgprint(final_message);
			}
		}
	}

	bill_date() {
		return this.posting_date();
	}

	recalculate_terms() {
		const doc = this.frm.doc;
		if (doc.payment_terms_template) {
			this.payment_terms_template();
		} else if (doc.payment_schedule) {
			const me = this;
			doc.payment_schedule.forEach(
				function(term) {
					if (term.payment_term) {
						me.payment_term(doc, term.doctype, term.name);
					} else {
						frappe.model.set_value(
							term.doctype, term.name, 'due_date',
							doc.posting_date || doc.transaction_date
						);
					}
				}
			);
		}
	}

	get_company_currency() {
		return erpnext.get_currency(this.frm.doc.company);
	}

	contact_person() {
		erpnext.utils.get_contact_details(this.frm);
	}

	currency() {
		/* manqala 19/09/2016: let the translation date be whichever of the transaction_date or posting_date is available */
		var transaction_date = this.frm.doc.transaction_date || this.frm.doc.posting_date;
		/* end manqala */
		var me = this;
		this.set_dynamic_labels();
		var company_currency = this.get_company_currency();
		// Added `ignore_pricing_rule` to determine if document is loading after mapping from another doc
		if(this.frm.doc.currency && this.frm.doc.currency !== company_currency
				&& !this.frm.doc.ignore_pricing_rule) {

			this.get_exchange_rate(transaction_date, this.frm.doc.currency, company_currency,
				function(exchange_rate) {
					if(exchange_rate != me.frm.doc.conversion_rate) {
						me.frm.set_value("conversion_rate", exchange_rate);
					}
				});
		} else {
			this.conversion_rate();
		}
	}

	conversion_rate() {
		const me = this.frm;
		if(this.frm.doc.currency === this.get_company_currency()) {
			this.frm.set_value("conversion_rate", 1.0);
		}
		if(this.frm.doc.currency === this.frm.doc.price_list_currency &&
			this.frm.doc.plc_conversion_rate &&
			this.frm.doc.plc_conversion_rate !== this.frm.doc.conversion_rate) {
			this.frm.set_value("plc_conversion_rate", this.frm.doc.conversion_rate);
		}

		if(flt(this.frm.doc.conversion_rate)>0.0) {
			if (cint(this.frm.doc.calculate_tax_on_company_currency)) {
				this.set_actual_charges_based_on_company_currency();
			}

			this.calculate_taxes_and_totals();
		}
		// Make read only if Accounts Settings doesn't allow stale rates
		this.frm.set_df_property("conversion_rate", "read_only", erpnext.stale_rate_allowed() ? 0 : 1);
	}

	set_actual_charges_based_on_company_currency() {
		var me = this;
		$.each(this.frm.doc.taxes || [], function(i, d) {
			if(d.charge_type == "Actual" || d.charge_type == "Weighted Distribution") {
				d.tax_amount = flt(d.base_tax_amount) / flt(me.frm.doc.conversion_rate);
			}
		});
	}

	get_exchange_rate(transaction_date, from_currency, to_currency, callback) {
		var args;
		if (["Quotation", "Sales Order", "Delivery Note", "Sales Invoice"].includes(this.frm.doctype)) {
			args = "for_selling";
		}
		else if (["Purchase Order", "Purchase Receipt", "Purchase Invoice"].includes(this.frm.doctype)) {
			args = "for_buying";
		}

		if (!transaction_date || !from_currency || !to_currency) return;
		return frappe.call({
			method: "erpnext.setup.utils.get_exchange_rate",
			args: {
				transaction_date: transaction_date,
				from_currency: from_currency,
				to_currency: to_currency,
				args: args
			},
			callback: function(r) {
				callback(flt(r.message));
			}
		});
	}

	price_list_currency() {
		var me=this;
		this.set_dynamic_labels();

		var company_currency = this.get_company_currency();
		// Added `ignore_pricing_rule` to determine if document is loading after mapping from another doc
		if(this.frm.doc.price_list_currency !== company_currency  && !this.frm.doc.ignore_pricing_rule) {
			this.get_exchange_rate(this.frm.doc.posting_date, this.frm.doc.price_list_currency, company_currency,
				function(exchange_rate) {
					me.frm.set_value("plc_conversion_rate", exchange_rate);
				});
		} else {
			this.plc_conversion_rate();
		}
	}

	plc_conversion_rate() {
		if(this.frm.doc.price_list_currency === this.get_company_currency()) {
			this.frm.set_value("plc_conversion_rate", 1.0);
		} else if(this.frm.doc.price_list_currency === this.frm.doc.currency
			&& this.frm.doc.plc_conversion_rate && cint(this.frm.doc.plc_conversion_rate) != 1 &&
			cint(this.frm.doc.plc_conversion_rate) != cint(this.frm.doc.conversion_rate)) {
			this.frm.set_value("conversion_rate", this.frm.doc.plc_conversion_rate);
		}
	}

	qty(doc, cdt, cdn) {
		let item = frappe.get_doc(cdt, cdn);
		this.conversion_factor(doc, cdt, cdn, true);
		this.apply_pricing_rule(item);
	}

	uom(doc, cdt, cdn) {
		let me = this;
		let item = frappe.get_doc(cdt, cdn);
		if (item.item_code && item.uom) {
			return this.frm.call({
				method: "erpnext.stock.get_item_details.get_conversion_factor",
				child: item,
				args: {
					item_code: item.item_code,
					uom: item.uom
				},
				callback: function(r) {
					if (!r.exc) {
						me.conversion_factor(me.frm.doc, cdt, cdn);
					}
				}
			});
		}
	}

	conversion_factor(doc, cdt, cdn, dont_fetch_price_list_rate) {
		if (!frappe.meta.get_docfield(cdt, "stock_qty", cdn)) {
			return;
		}

		let item = frappe.get_doc(cdt, cdn);

		frappe.model.round_floats_in(item, ["qty", "conversion_factor"]);
		item.stock_qty = flt(item.qty * item.conversion_factor, 6);

		if(doc.doctype == "Material Request") {
			this.calculate_total_qty();
		} else {
			this.calculate_taxes_and_totals();
			this.shipping_rule();
		}

		if (!dont_fetch_price_list_rate && frappe.meta.has_field(doc.doctype, "price_list_currency")) {
			this.apply_price_list(item, true);
		}
	}

	weight_uom(doc, cdt, cdn) {
		let item = frappe.get_doc(cdt, cdn);

		if (item.item_code && item.weight_uom) {
			return this.frm.call({
				method: "erpnext.stock.get_item_details.get_weight_per_unit",
				args: {
					item_code: item.item_code,
					weight_uom: item.weight_uom
				},
				callback: function(r) {
					if (!r.exc) {
						frappe.model.set_value(cdt, cdn, "net_weight_per_unit", flt(r.message));
					}
				}
			});
		}
	}

	net_weight_per_unit(doc, cdt, cdn) {
		let item = frappe.get_doc(cdt, cdn);
		item.net_weight = flt(flt(item.net_weight_per_unit) * flt(item.stock_qty), precision("net_weight", item));
		this.calculate_taxes_and_totals();
		this.shipping_rule();
	}

	shipping_rule() {
		let me = this;
		if (this.frm.doc.shipping_rule) {
			return this.frm.call({
				doc: this.frm.doc,
				method: "apply_shipping_rule",
				callback: function(r) {
					if(!r.exc) {
						me.calculate_taxes_and_totals();
					}
				}
			}).fail(() => this.frm.set_value('shipping_rule', ''));
		}
	}

	tax_exclusive_rate(doc, cdt, cdn) {
		var item = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "rate", item.tax_exclusive_rate * (1 + item.cumulated_tax_fraction));
	}

	service_stop_date(frm, cdt, cdn) {
		var child = locals[cdt][cdn];

		if(child.service_stop_date) {
			let start_date = Date.parse(child.service_start_date);
			let end_date = Date.parse(child.service_end_date);
			let stop_date = Date.parse(child.service_stop_date);

			if(stop_date < start_date) {
				frappe.model.set_value(cdt, cdn, "service_stop_date", "");
				frappe.throw(__("Service Stop Date cannot be before Service Start Date"));
			} else if (stop_date > end_date) {
				frappe.model.set_value(cdt, cdn, "service_stop_date", "");
				frappe.throw(__("Service Stop Date cannot be after Service End Date"));
			}
		}
	}

	service_start_date(frm, cdt, cdn) {
		var child = locals[cdt][cdn];

		if(child.service_start_date) {
			frappe.call({
				"method": "erpnext.stock.get_item_details.calculate_service_end_date",
				args: {"args": child},
				callback: function(r) {
					frappe.model.set_value(cdt, cdn, "service_end_date", r.message.service_end_date);
				}
			})
		}
	}

	vehicle_owner() {
		if (!this.frm.doc.vehicle_owner) {
			this.frm.doc.vehicle_owner_name = null;
		}
	}

	vehicle_chassis_no() {
		erpnext.utils.format_vehicle_id(this.frm, 'vehicle_chassis_no');
	}
	vehicle_engine_no() {
		erpnext.utils.format_vehicle_id(this.frm, 'vehicle_engine_no');
	}
	vehicle_license_plate() {
		erpnext.utils.format_vehicle_id(this.frm, 'vehicle_license_plate');
	}

	set_dynamic_labels() {
		// What TODO? should we make price list system non-mandatory?
		this.frm.toggle_reqd("plc_conversion_rate",
			!!(this.frm.doc.price_list_name && this.frm.doc.price_list_currency));

		var company_currency = this.get_company_currency();
		this.change_form_labels(company_currency);
		this.change_grid_labels(company_currency);
		this.frm.refresh_fields();
	}

	change_form_labels(company_currency) {
		let me = this;

		this.frm.set_currency_labels([
			"base_total", "base_net_total", "base_taxable_total", "base_retail_total",
			"base_total_taxes_and_charges", "base_total_discount_after_taxes", "base_total_after_taxes",
			"base_discount_amount", "base_grand_total", "base_rounded_total", "base_in_words",
			"base_taxes_and_charges_added", "base_taxes_and_charges_deducted", "total_amount_to_pay",
			"base_paid_amount", "base_write_off_amount", "base_change_amount", "base_operating_cost",
			"base_raw_material_cost", "base_total_cost", "base_scrap_material_cost",
			"base_total_operating_cost", "base_additional_operating_cost",
			"base_rounding_adjustment", "base_tax_exclusive_total",
			"base_total_before_discount", "base_tax_exclusive_total_before_discount",
			"base_total_discount", "base_tax_exclusive_total_discount",
			"base_total_before_depreciation", "base_tax_exclusive_total_before_depreciation",
			"base_total_depreciation", "base_tax_exclusive_total_depreciation",
			"base_total_underinsurance", "base_tax_exclusive_total_underinsurance",
		], company_currency);

		this.frm.set_currency_labels([
			"total", "net_total", "taxable_total", "retail_total", "total_taxes_and_charges",
			"discount_amount", "grand_total", "total_discount_after_taxes", "total_after_taxes",
			"taxes_and_charges_added", "taxes_and_charges_deducted",
			"rounded_total", "in_words", "paid_amount", "write_off_amount", "change_amount", "operating_cost",
			"scrap_material_cost", "rounding_adjustment", "raw_material_cost",
			"total_operating_cost", "additional_operating_cost",
			"total_cost", "tax_exclusive_total",
			"total_before_discount", "tax_exclusive_total_before_discount",
			"total_discount", "tax_exclusive_total_discount",
			"total_before_depreciation", "tax_exclusive_total_before_depreciation",
			"total_depreciation", "tax_exclusive_total_depreciation",
			"total_underinsurance", "tax_exclusive_total_underinsurance",
		], this.frm.doc.currency);

		if (this.frm.doc.doctype === "Sales Invoice") {
			this.frm.set_currency_labels(["customer_outstanding_amount", "previous_outstanding_amount"],
				this.frm.doc.party_account_currency);
		} else {
			this.frm.set_currency_labels(["customer_outstanding_amount", "customer_credit_limit",
				"customer_credit_balance"], company_currency);
		}

		this.frm.set_currency_labels(["outstanding_amount", "total_advance"],
			this.frm.doc.party_account_currency);

		cur_frm.set_df_property("conversion_rate", "description", "1 " + this.frm.doc.currency
			+ " = [?] " + company_currency);

		if(this.frm.doc.price_list_currency && this.frm.doc.price_list_currency!=company_currency) {
			cur_frm.set_df_property("plc_conversion_rate", "description", "1 "
				+ this.frm.doc.price_list_currency + " = [?] " + company_currency);
		}

		// toggle fields
		this.frm.toggle_display([
			"conversion_rate", "base_total", "base_net_total", "base_taxable_total", "base_retail_total",
			"base_total_discount_after_taxes", "base_total_after_taxes",
			"base_total_taxes_and_charges", "base_taxes_and_charges_added", "base_taxes_and_charges_deducted",
			"base_grand_total", "base_rounded_total", "base_in_words",
			"base_paid_amount", "base_change_amount", "base_write_off_amount", "base_operating_cost", "base_raw_material_cost",
			"base_total_operating_cost", "base_additional_operating_cost",
			"base_total_cost", "base_scrap_material_cost", "base_rounding_adjustment",
			"base_total_before_discount", "base_total_discount",
			"base_total_before_depreciation", "base_total_depreciation", "base_total_underinsurance",
			"calculate_tax_on_company_currency"
		], this.frm.doc.currency != company_currency, true);

		this.frm.toggle_display(["plc_conversion_rate", "price_list_currency"],
			this.frm.doc.price_list_currency != company_currency, true);

		var show_exclusive = (cur_frm.doc.taxes || []).filter(function(d) {return d.included_in_print_rate===1}).length;

		$.each([
			"tax_exclusive_total", "tax_exclusive_total_before_discount", "tax_exclusive_total_discount",
			"tax_exclusive_total_before_depreciation", "tax_exclusive_total_depreciation", "tax_exclusive_total_underinsurance",
		], function(i, fname) {
			if(frappe.meta.get_docfield(cur_frm.doctype, fname))
				cur_frm.toggle_display(fname, show_exclusive, true);
		});

		$.each([
			"base_tax_exclusive_total",
			"base_tax_exclusive_total_before_discount", "base_tax_exclusive_total_discount",
			"base_tax_exclusive_total_before_depreciation",
			"base_tax_exclusive_total_depreciation", "base_tax_exclusive_total_underinsurance",
		], function(i, fname) {
			if(frappe.meta.get_docfield(cur_frm.doctype, fname))
				cur_frm.toggle_display(fname, show_exclusive && (me.frm.doc.currency != company_currency), true);
		});

		var apply_taxes_on_retail = (cur_frm.doc.items || []).filter(d => cint(d.apply_taxes_on_retail)).length
			&& (cur_frm.doc.taxes || []).filter(d => d.tax_amount).length;
		var show_net = cint(cur_frm.doc.discount_amount) || apply_taxes_on_retail || show_exclusive;

		if(frappe.meta.get_docfield(cur_frm.doctype, "net_total"))
			cur_frm.toggle_display("net_total", show_net, true);

		if(frappe.meta.get_docfield(cur_frm.doctype, "base_net_total"))
			cur_frm.toggle_display("base_net_total", (show_net && (me.frm.doc.currency != company_currency)), true);

		$.each(["base_discount_amount"], function(i, fname) {
			if(frappe.meta.get_docfield(cur_frm.doctype, fname))
				cur_frm.toggle_display(fname, me.frm.doc.currency != company_currency, true);
		});
	}

	change_grid_labels(company_currency) {
		var me = this;

		this.frm.set_currency_labels([
			"base_price_list_rate", "base_rate", "base_net_rate", "base_taxable_rate", "base_alt_uom_rate",
			"base_amount", "base_net_amount", "base_taxable_amount",
			"base_rate_with_margin", "base_tax_exclusive_price_list_rate",
			"base_tax_exclusive_rate", "base_tax_exclusive_amount", "base_tax_exclusive_rate_with_margin",
			"base_amount_before_discount", "base_tax_exclusive_amount_before_discount",
			"base_item_taxes_before_discount", "base_tax_inclusive_amount_before_discount", "base_tax_inclusive_rate_before_discount",
			"base_total_discount", "base_tax_exclusive_total_discount",
			"base_amount_before_depreciation", "base_depreciation_amount", "base_underinsurance_amount",
			"base_tax_exclusive_amount_before_depreciation", "base_tax_exclusive_depreciation_amount", "base_tax_exclusive_underinsurance_amount",
			"base_returned_amount",
			"base_retail_rate", "base_retail_amount"
		], company_currency, "items");

		this.frm.set_currency_labels([
			"price_list_rate", "rate", "net_rate", "taxable_rate", "alt_uom_rate",
			"amount", "net_amount", "taxable_amount", "rate_with_margin",
			"discount_amount", "tax_exclusive_price_list_rate", "tax_exclusive_rate", "tax_exclusive_amount",
			"tax_exclusive_discount_amount", "tax_exclusive_rate_with_margin",
			"amount_before_discount", "tax_exclusive_amount_before_discount",
			"item_taxes_before_discount", "tax_inclusive_amount_before_discount", "tax_inclusive_rate_before_discount",
			"total_discount", "tax_exclusive_total_discount",
			"amount_before_depreciation", "depreciation_amount", "underinsurance_amount",
			"tax_exclusive_amount_before_depreciation", "tax_exclusive_depreciation_amount", "tax_exclusive_underinsurance_amount",
			"retail_rate", "retail_amount"
		], this.frm.doc.currency, "items");

		if(this.frm.fields_dict["operations"]) {
			this.frm.set_currency_labels(["operating_cost", "hour_rate"], this.frm.doc.currency, "operations");
			this.frm.set_currency_labels(["base_operating_cost", "base_hour_rate"], company_currency, "operations");

			let item_grid = this.frm.fields_dict["operations"].grid;
			$.each(["base_operating_cost", "base_hour_rate"], function(i, fname) {
				if(frappe.meta.get_docfield(item_grid.doctype, fname))
					item_grid.set_column_disp(fname, me.frm.doc.currency != company_currency, true);
			});
		}

		if(this.frm.fields_dict["scrap_items"]) {
			this.frm.set_currency_labels(["rate", "amount"], this.frm.doc.currency, "scrap_items");
			this.frm.set_currency_labels(["base_rate", "base_amount"], company_currency, "scrap_items");

			let item_grid = this.frm.fields_dict["scrap_items"].grid;
			$.each(["base_rate", "base_amount"], function(i, fname) {
				if(frappe.meta.get_docfield(item_grid.doctype, fname))
					item_grid.set_column_disp(fname, me.frm.doc.currency != company_currency, true);
			});
		}

		if(this.frm.fields_dict["additional_costs"]) {
			this.frm.set_currency_labels(["rate", "amount"], this.frm.doc.currency, "additional_costs");
			this.frm.set_currency_labels(["base_rate", "base_amount"], company_currency, "additional_costs");

			var additional_costs_grid = this.frm.fields_dict["additional_costs"].grid;
			$.each(["base_rate", "base_amount"], function(i, fname) {
				if(frappe.meta.get_docfield(additional_costs_grid.doctype, fname))
					additional_costs_grid.set_column_disp(fname, me.frm.doc.currency != company_currency, true);
			});
		}

		if(this.frm.fields_dict["taxes"]) {
			this.frm.set_currency_labels(["tax_amount", "total", "tax_amount_after_discount_amount",
				"displayed_total"], this.frm.doc.currency, "taxes");

			this.frm.set_currency_labels(["base_tax_amount", "base_total", "base_tax_amount_after_discount_amount",
				"base_displayed_total"], company_currency, "taxes");
		}

		if(this.frm.fields_dict["advances"]) {
			this.frm.set_currency_labels(["advance_amount", "allocated_amount"],
				this.frm.doc.party_account_currency, "advances");
		}

		// toggle columns
		if(this.frm.fields_dict["taxes"]) {
			var tax_grid = this.frm.fields_dict["taxes"].grid;
			$.each(["base_tax_amount", "base_total", "base_tax_amount_after_discount_amount",
			"base_displayed_total"], function(i, fname) {
				if(frappe.meta.get_docfield(tax_grid.doctype, fname))
					tax_grid.set_column_disp(fname, me.frm.doc.currency != company_currency, true);
			});
		}

		let item_grid = this.frm.fields_dict["items"].grid;
		$.each([
			"base_rate", "base_price_list_rate", "base_amount", "base_rate_with_margin", "base_alt_uom_rate",
			"base_amount_before_discount", "base_total_discount",
			"base_amount_before_depreciation", "base_depreciation_amount", "base_underinsurance_amount",
			"base_item_taxes_before_discount", "base_tax_inclusive_amount_before_discount", "base_tax_inclusive_rate_before_discount",
			"base_retail_rate", "base_retail_amount"
		], function(i, fname) {
			if(frappe.meta.get_docfield(item_grid.doctype, fname))
				item_grid.set_column_disp(fname, me.frm.doc.currency != company_currency, true);
		});

		var show_exclusive = (cur_frm.doc.taxes || []).filter(function(d) {return d.included_in_print_rate===1}).length;

		$.each([
			"tax_exclusive_price_list_rate", "tax_exclusive_rate", "tax_exclusive_amount",
			"tax_exclusive_discount_amount", "tax_exclusive_rate_with_margin",
			"tax_exclusive_amount_before_discount", "tax_exclusive_total_discount",
			"tax_exclusive_amount_before_depreciation", "tax_exclusive_depreciation_amount", "tax_exclusive_underinsurance_amount",
		], function(i, fname) {
			if(frappe.meta.get_docfield(item_grid.doctype, fname))
				item_grid.set_column_disp(fname, show_exclusive, true);
		});

		$.each([
			"base_tax_exclusive_price_list_rate", "base_tax_exclusive_rate", "base_tax_exclusive_amount",
			"base_tax_exclusive_rate_with_margin",
			"base_tax_exclusive_amount_before_discount", "base_tax_exclusive_total_discount",
			"base_tax_exclusive_amount_before_depreciation", "base_tax_exclusive_depreciation_amount", "base_tax_exclusive_underinsurance_amount",
		], function(i, fname) {
			if(frappe.meta.get_docfield(item_grid.doctype, fname))
				item_grid.set_column_disp(fname, (show_exclusive && (me.frm.doc.currency != company_currency)), true);
		});

		var apply_taxes_on_retail = (cur_frm.doc.items || []).filter(d => cint(d.apply_taxes_on_retail)).length;
		var show_net = cint(cur_frm.doc.discount_amount) || apply_taxes_on_retail || show_exclusive;

		$.each(["taxable_rate", "taxable_amount", "net_rate", "net_amount"], function(i, fname) {
			if(frappe.meta.get_docfield(item_grid.doctype, fname))
				item_grid.set_column_disp(fname, show_net, true);
		});

		$.each(["base_taxable_rate", "base_taxable_amount", "base_net_rate", "base_net_amount"], function(i, fname) {
			if(frappe.meta.get_docfield(item_grid.doctype, fname))
				item_grid.set_column_disp(fname, (show_net && (me.frm.doc.currency != company_currency)), true);
		});

		// set labels
		var $wrapper = $(this.frm.wrapper);
	}

	recalculate() {
		this.calculate_taxes_and_totals();
	}

	recalculate_values() {
		this.calculate_taxes_and_totals();
	}

	calculate_charges() {
		this.calculate_taxes_and_totals();
	}

	disable_rounded_total() {
		this.calculate_taxes_and_totals();
	}

	ignore_pricing_rule() {
		if(this.frm.doc.ignore_pricing_rule) {
			var me = this;
			var item_list = [];

			$.each(this.frm.doc["items"] || [], function(i, d) {
				if (d.item_code && !d.is_free_item) {
					item_list.push({
						"doctype": d.doctype,
						"name": d.name,
						"item_code": d.item_code,
						"pricing_rules": d.pricing_rules,
						"parenttype": d.parenttype,
						"parent": d.parent
					})
				}
			});
			return this.frm.call({
				method: "erpnext.accounts.doctype.pricing_rule.pricing_rule.remove_pricing_rules",
				args: { item_list: item_list },
				callback: function(r) {
					if (!r.exc && r.message) {
						r.message.forEach(row_item => {
							me.remove_pricing_rule(row_item);
						});
						me._set_values_for_item_list(r.message);
						me.calculate_taxes_and_totals();
						if(me.frm.doc.apply_discount_on) me.frm.trigger("apply_discount_on");
					}
				}
			});
		} else {
			this.apply_pricing_rule();
		}
	}

	apply_pricing_rule(item) {
		let me = this;
		let args = this._get_args(item);
		if (!args.items || !args.items.length) {
			return;
		}

		return this.frm.call({
			method: "erpnext.accounts.doctype.pricing_rule.pricing_rule.apply_pricing_rule",
			args: {
				args: args,
				doc: me.frm.doc
			},
			callback: function(r) {
				if (!r.exc && r.message) {
					me._set_values_for_item_list(r.message);
					if (item) {
						me.set_gross_profit(item);
					}
				}
			}
		});
	}

	_get_args(item) {
		var me = this;
		return {
			"items": this._get_item_list(item),
			"customer": me.frm.doc.customer || me.frm.doc.party_name,
			"bill_to": me.frm.doc.bill_to,
			"quotation_to": me.frm.doc.quotation_to,
			"customer_group": me.frm.doc.customer_group,
			"territory": me.frm.doc.territory,
			"supplier": me.frm.doc.supplier,
			"supplier_group": me.frm.doc.supplier_group,
			"currency": me.frm.doc.currency,
			"conversion_rate": me.frm.doc.conversion_rate,
			"retail_price_list": me.frm.doc.retail_price_list,
			"price_list": me.frm.doc.selling_price_list || me.frm.doc.buying_price_list,
			"price_list_currency": me.frm.doc.price_list_currency,
			"plc_conversion_rate": me.frm.doc.plc_conversion_rate,
			"company": me.frm.doc.company,
			"transaction_date": me.frm.doc.transaction_date || me.frm.doc.posting_date,
			"transaction_type_name": me.frm.doc.transaction_type,
			"campaign": me.frm.doc.campaign,
			"sales_partner": me.frm.doc.sales_partner,
			"ignore_pricing_rule": me.frm.doc.ignore_pricing_rule,
			"doctype": me.frm.doc.doctype,
			"name": me.frm.doc.name,
			"is_return": cint(me.frm.doc.is_return),
			"update_stock": in_list(['Sales Invoice', 'Purchase Invoice'], me.frm.doc.doctype) ? cint(me.frm.doc.update_stock) : 0,
			"conversion_factor": me.frm.doc.conversion_factor,
			"pos_profile": me.frm.doc.doctype == 'Sales Invoice' ? me.frm.doc.pos_profile : '',
			"coupon_code": me.frm.doc.coupon_code
		};
	}

	_get_item_list(item) {
		var item_list = [];
		var append_item = function(d) {
			if (d.item_code) {
				let item_args = {
					"doctype": d.doctype,
					"name": d.name,
					"child_docname": d.name,
					"item_code": d.item_code,
					"item_group": d.item_group,
					"brand": d.brand,
					"qty": d.qty,
					"stock_qty": d.stock_qty,
					"uom": d.uom,
					"stock_uom": d.stock_uom,
					"net_weight_per_unit": d.net_weight_per_unit,
					"net_weight": d.net_weight,
					"weight_uom": d.weight_uom,
					"parenttype": d.parenttype,
					"parent": d.parent,
					"pricing_rules": d.pricing_rules,
					"batch_no": d.batch_no,
					"warehouse": d.warehouse,
					"serial_no": d.serial_no,
					"discount_percentage": d.discount_percentage || 0.0,
					"price_list_rate": d.price_list_rate,
					"conversion_factor": d.conversion_factor || 1.0,
					"apply_taxes_on_retail": d.apply_taxes_on_retail,
					"allow_zero_valuation_rate": d.allow_zero_valuation_rate
				}

				// if doctype is Quotation Item / Sales Order Iten then add Margin Type and rate in item_list
				if (frappe.meta.has_field(d.doctype, 'margin_type')) {
					item_args["margin_type"] = d.margin_type;
					item_args["margin_rate_or_amount"] = d.margin_rate_or_amount;
				}

				for (let func of erpnext.update_item_args_for_pricing_hooks || []) {
					func.apply(this, [d, item_args]);
				}

				item_list.push(item_args);
			}
		};

		if (item) {
			append_item(item);
		} else {
			$.each(this.frm.doc["items"] || [], function(i, d) {
				append_item(d);
			});
		}
		return item_list;
	}

	_set_values_for_item_list(children) {
		let me = this;
		let items_rule_dict = {};

		for (let d of children) {
			let existing_pricing_rule = frappe.model.get_value(d.doctype, d.name, "pricing_rules");
			for (let [k, v] of Object.entries(d)) {
				if (
					!["doctype", "name", "parent", "parenttype", "discount_amount", "discount_percentage"].includes(k)
					&& frappe.meta.has_field(d.doctype, k)
				) {
					frappe.model.set_value(d.doctype, d.child_docname || d.name, k, v);
				}
			}

			if (d.pricing_rule_for == "Discount Amount") {
				frappe.model.set_value(d.doctype, d.child_docname || d.name, "discount_amount", d.discount_amount);
			} else {
				frappe.model.set_value(d.doctype, d.child_docname || d.name, "discount_percentage", d.discount_percentage);
			}

			// if pricing rule set as blank from an existing value, apply price_list
			if (!me.frm.doc.ignore_pricing_rule && existing_pricing_rule && !d.pricing_rules) {
				me.apply_price_list(frappe.get_doc(d.doctype, d.name));
			} else if (!d.pricing_rules) {
				me.remove_pricing_rule(frappe.get_doc(d.doctype, d.name));
			}

			if (d.free_item_data) {
				me.apply_product_discount(d.free_item_data);
			}

			if (d.apply_rule_on_other_items) {
				items_rule_dict[d.name] = d;
			}
		}

		me.apply_rule_on_other_items(items_rule_dict);
	}

	apply_rule_on_other_items(args) {
		const me = this;
		const fields = ["discount_percentage", "pricing_rules", "discount_amount", "rate"];

		for(var k in args) {
			let data = args[k];

			if (data && data.apply_rule_on_other_items) {
				me.frm.doc.items.forEach(d => {
					if (in_list(JSON.parse(data.apply_rule_on_other_items), d[data.apply_rule_on])) {
						for(var k in data) {
							if (in_list(fields, k) && data[k] && (data.price_or_product_discount === 'Price' || k === 'pricing_rules')) {
								frappe.model.set_value(d.doctype, d.name, k, data[k]);
							}
						}
					}
				});
			}
		}
	}

	apply_product_discount(free_item_data) {
		const items = this.frm.doc.items.filter(d => (d.item_code == free_item_data.item_code
			&& d.is_free_item)) || [];

		if (!items.length) {
			let row_to_modify = frappe.model.add_child(this.frm.doc,
				this.frm.doc.doctype + ' Item', 'items');

			for (let key in free_item_data) {
				row_to_modify[key] = free_item_data[key];
			}
		} if (items && items.length && free_item_data) {
			items[0].qty = free_item_data.qty
		}
	}

	apply_price_list(item, reset_plc_conversion) {
		// We need to reset plc_conversion_rate sometimes because the call to
		// `erpnext.stock.get_item_details.apply_price_list` is sensitive to its value
		if (!reset_plc_conversion) {
			this.frm.set_value("plc_conversion_rate", "");
		}

		var me = this;
		var args = this._get_args(item);
		if (!args.items || !args.items.length || !args.price_list) {
			return;
		}

		if (me.in_apply_price_list == true) return;

		me.in_apply_price_list = true;
		return this.frm.call({
			method: "erpnext.stock.get_item_details.apply_price_list",
			args: {	args: args },
			callback: function(r) {
				if (!r.exc) {
					frappe.run_serially([
						() => me.frm.set_value("price_list_currency", r.message.parent.price_list_currency),
						() => me.frm.set_value("plc_conversion_rate", r.message.parent.plc_conversion_rate),
						() => {
							if (args.items.length) {
								me._set_values_for_item_list(r.message.children);
								me.calculate_taxes_and_totals();
							}
						},
						() => { me.in_apply_price_list = false; }
					]);

				} else {
					me.in_apply_price_list = false;
				}
			}
		}).always(() => {
			me.in_apply_price_list = false;
		});
	}

	get_latest_price() {
		this.apply_price_list();
	}

	remove_pricing_rule(item) {
		let me = this;
		const fields = ["discount_percentage",
			"discount_amount", "margin_rate_or_amount", "rate_with_margin"];

		if(item.remove_free_item) {
			var items = [];

			me.frm.doc.items.forEach(d => {
				if(d.item_code != item.remove_free_item || !d.is_free_item) {
					items.push(d);
				}
			});

			me.frm.doc.items = items;
			refresh_field('items');
		} else if(item.applied_on_items && item.apply_on) {
			const applied_on_items = JSON.parse(item.applied_on_items);
			me.frm.doc.items.forEach(row => {
				if(in_list(applied_on_items, row[item.apply_on])) {
					fields.forEach(f => {
						row[f] = 0;
					});

					["pricing_rules", "margin_type"].forEach(field => {
						if (row[field]) {
							row[field] = '';
						}
					})
				}
			});

			me.trigger_price_list_rate();
		}
	}

	trigger_price_list_rate() {
		var me  = this;

		this.frm.doc.items.forEach(child_row => {
			me.frm.script_manager.trigger("price_list_rate",
				child_row.doctype, child_row.name);
		})
	}

	validate_company_and_party() {
		var me = this;
		var valid = true;

		$.each(["company", "customer"], function(i, fieldname) {
			if(frappe.meta.has_field(me.frm.doc.doctype, fieldname) && me.frm.doc.doctype != "Purchase Order") {
				if (!me.frm.doc[fieldname]) {
					frappe.msgprint(__("Please specify") + ": " +
						frappe.meta.get_label(me.frm.doc.doctype, fieldname, me.frm.doc.name) +
						". " + __("It is needed to fetch Item Details."));
					valid = false;
				}
			}
		});
		return valid;
	}

	get_terms() {
		var me = this;

		erpnext.utils.get_terms(this.frm.doc.tc_name, this.frm.doc, function(r) {
			if(!r.exc) {
				me.frm.set_value("terms", r.message);
			}
		});
	}

	taxes_and_charges() {
		var me = this;
		if(this.frm.doc.taxes_and_charges) {
			return this.frm.call({
				method: "erpnext.controllers.transaction_controller.get_taxes_and_charges",
				args: {
					"master_doctype": frappe.meta.get_docfield(this.frm.doc.doctype, "taxes_and_charges",
						this.frm.doc.name).options,
					"master_name": this.frm.doc.taxes_and_charges
				},
				callback: function(r) {
					if(!r.exc) {
						if(me.frm.doc.shipping_rule && me.frm.doc.taxes) {
							for (let tax of r.message) {
								me.frm.add_child("taxes", tax);
							}

							refresh_field("taxes");
						} else {
							me.frm.set_value("taxes", r.message);
							me.calculate_taxes_and_totals();
						}
					}
				}
			});
		}
	}

	tax_category() {
		if (this.frm.updating_party_details) {
			return;
		}

		return frappe.run_serially([
			() => this.update_item_tax_templates(true),
			() => erpnext.utils.set_taxes(this.frm, "tax_category"),
		]);
	}

	item_tax_template(doc, cdt, cdn) {
		let item = frappe.get_doc(cdt, cdn);
		return this.get_item_tax_template(item);
	}

	get_item_tax_template(item) {
		let me = this;

		if (item.item_tax_template) {
			return this.frm.call({
				method: "erpnext.stock.get_item_details.get_item_tax_map",
				args: {
					item_tax_template: item.item_tax_template,
					company: me.frm.doc.company,
					transaction_date: me.frm.doc.bill_date || me.frm.doc.transaction_date || me.frm.doc.posting_date,
					as_json: 1
				},
				callback: function(r) {
					if (!r.exc) {
						item.item_tax_rate = r.message;
						me.add_taxes_from_item_tax_template(item.item_tax_rate);
						me.calculate_taxes_and_totals();
					}
				}
			});
		} else {
			item.item_tax_rate = "{}";
			me.calculate_taxes_and_totals();
		}
	}

	update_item_tax_map() {
		let me = this;
		let item_tax_templates = (this.frm.doc.items || []).map(d => d.item_tax_template).filter(d => d);

		if (me.frm.doc.company && item_tax_templates.length) {
			return this.frm.call({
				method: "erpnext.stock.get_item_details.get_multiple_item_tax_maps",
				args: {
					item_tax_templates: item_tax_templates,
					company: me.frm.doc.company,
					transaction_date: me.frm.doc.bill_date || me.frm.doc.transaction_date || me.frm.doc.posting_date,
					as_json: 1
				},
				callback: function(r) {
					if (!r.exc) {
						$.each(me.frm.doc.items || [], function(i, item) {
							if (item.item_tax_template && r.message.hasOwnProperty(item.item_tax_template)) {
								item.item_tax_rate = r.message[item.item_tax_template];
								me.add_taxes_from_item_tax_template(item.item_tax_rate);
							}
						});
						me.calculate_taxes_and_totals();
					}
				}
			});
		}
	}

	update_item_tax_templates() {
		let me = this;
		let item_codes = (this.frm.doc.items || []).map(d => d.item_code).filter(d => d);

		if (me.frm.doc.company && item_codes.length) {
			return this.frm.call({
				method: "erpnext.stock.get_item_details.get_multiple_item_tax_templates",
				args: {
					args: {
						company: me.frm.doc.company,
						tax_category: cstr(me.frm.doc.tax_category),
						transaction_date: me.frm.doc.transaction_date,
						posting_date: me.frm.doc.posting_date,
						bill_date: me.frm.doc.bill_date,
					},
					item_codes: item_codes
				},
				callback: function(r) {
					if (!r.exc) {
						$.each(me.frm.doc.items || [], function(i, item) {
							if(item.item_code && r.message.hasOwnProperty(item.item_code)) {
								item.item_tax_template = r.message[item.item_code].item_tax_template;
								item.item_tax_rate = r.message[item.item_code].item_tax_rate;
								me.add_taxes_from_item_tax_template(item.item_tax_rate);
							} else {
								item.item_tax_template = null;
								item.item_tax_rate = "{}";
							}
						});
						me.calculate_taxes_and_totals();
					}
				}
			});
		}
	}

	get_item_defaults_args() {
		var me = this;
		var items = [];

		$.each(this.frm.doc.items || [], function(i, item) {
			if(item.item_code) {
				items.push({
					name: item.name,
					item_code: item.item_code,
					cost_center: item.cost_center,
					income_account: item.income_account,
					expense_account: item.expense_account,
					apply_taxes_on_retail: item.apply_taxes_on_retail,
					allow_zero_valuation_rate: me.allow_zero_valuation_rate,
					project: item.project || me.frm.doc.project,
					warehouse: item.warehouse
				});
			}
		});

		return {
			args: {
				doctype: me.frm.doc.doctype,
				company: me.frm.doc.company,
				transaction_type_name: me.frm.doc.transaction_type,
				customer: me.frm.doc.customer,
				supplier: me.frm.doc.supplier,
				project: me.frm.doc.project,
				set_warehouse: me.frm.doc.set_warehouse
			},
			items: items
		};
	}

	update_item_defaults(set_warehouse, row) {
		var me = this;
		var args = me.get_item_defaults_args();
		args['set_warehouse'] = cint(set_warehouse);

		if(args.items.length) {
			return frappe.call({
				method: "erpnext.stock.get_item_details.get_item_defaults_info",
				args: args,
				callback: function(r) {
					if(!r.exc) {
						me.set_item_defaults(r.message);
					}
				}
			});
		}
	}

	set_item_defaults(items_dict) {
		var me = this;
		$.each(me.frm.doc.items || [], function(i, item) {
			if(item.item_code && items_dict.hasOwnProperty(item.name)) {
				if (items_dict[item.name].warehouse && item.packing_slip) {
					delete items_dict[item.name]["warehouse"];
				}

				frappe.model.set_value(item.doctype, item.name, items_dict[item.name]);
			}
		});
	}

	transaction_type() {
		var me = this;

		var args = me.get_item_defaults_args();
		args.args.letter_of_credit = me.frm.doc.letter_of_credit;
		args.args.bill_to = me.frm.doc.bill_to;

		return frappe.call({
			method: "erpnext.accounts.doctype.transaction_type.transaction_type.get_transaction_type_details",
			args: args,
			callback: function(r) {
				if(!r.exc) {
					me.set_item_defaults(r.message.items);

					$.each(r.message.doc || {}, function (k, v) {
						if (me.frm.fields_dict[k]) {
							if (k === 'cost_center') {
								me.frm.doc[k] = v;
								me.frm.refresh_field('cost_center');
							} else {
								me.frm.set_value(k, v);
							}
						}
					});

					erpnext.utils.set_taxes(me.frm, 'transaction_type');
				}
			}
		});
	}

	cost_center(doc, cdt, cdn) {
		if (cdt !== this.frm.doc.doctype) {
			return;
		}
		erpnext.utils.set_taxes(this.frm, 'cost_center');
	}

	has_stin() {
		erpnext.utils.set_taxes(this.frm, 'has_stin');
	}

	is_recurring() {
		// set default values for recurring documents
		if(this.frm.doc.is_recurring && this.frm.doc.__islocal) {
			frappe.msgprint(__("Please set recurring after saving"));
			this.frm.set_value('is_recurring', 0);
			return;
		}

		if(this.frm.doc.is_recurring) {
			if(!this.frm.doc.recurring_id) {
				this.frm.set_value('recurring_id', this.frm.doc.name);
			}

			var owner_email = this.frm.doc.owner=="Administrator"
				? frappe.user_info("Administrator").email
				: this.frm.doc.owner;

			this.frm.doc.notification_email_address = $.map([cstr(owner_email),
				cstr(this.frm.doc.contact_email)], function(v) { return v || null; }).join(", ");
			this.frm.doc.repeat_on_day_of_month = frappe.datetime.str_to_obj(this.frm.doc.posting_date).getDate();
		}

		refresh_many(["notification_email_address", "repeat_on_day_of_month"]);
	}

	from_date() {
		// set to_date
		if(this.frm.doc.from_date) {
			var recurring_type_map = {'Monthly': 1, 'Quarterly': 3, 'Half-yearly': 6,
				'Yearly': 12};

			var months = recurring_type_map[this.frm.doc.recurring_type];
			if(months) {
				var to_date = frappe.datetime.add_months(this.frm.doc.from_date,
					months);
				this.frm.doc.to_date = frappe.datetime.add_days(to_date, -1);
				refresh_field('to_date');
			}
		}
	}

	set_item_rate(item) {
		let margin_df = frappe.meta.get_docfield(item.doctype, 'margin_type');

		if (item.price_list_rate) {
			if(item.rate > item.price_list_rate && margin_df) {
				// if rate is greater than price_list_rate, set margin
				// or set discount
				item.discount_amount = 0;
				item.discount_percentage = 0;

				if (!['Amount', 'Percentage'].includes(item.margin_type)) {
					item.margin_type = margin_df['default'] || 'Amount';
				}
				if (item.margin_type === 'Amount') {
					item.margin_rate_or_amount = flt(item.rate - item.price_list_rate);
				} else {
					item.margin_rate_or_amount = (item.rate / item.price_list_rate - 1) * 100;
				}
				item.rate_with_margin = item.rate;
			} else {
				item.discount_amount = flt(item.price_list_rate - item.rate);
				item.discount_percentage = flt((1 - item.rate / item.price_list_rate) * 100.0);
				item.discount_amount = flt(item.price_list_rate) - flt(item.rate);
				item.margin_type = '';
				item.margin_rate_or_amount = 0;
				item.rate_with_margin = 0;
			}
		} else {
			item.discount_amount = 0;
			item.discount_percentage = 0.0;
			item.margin_type = '';
			item.margin_rate_or_amount = 0;
			item.rate_with_margin = 0;
		}
		item.base_rate_with_margin = item.rate_with_margin * flt(this.frm.doc.conversion_rate);

		this.set_gross_profit(item);
	}

	set_gross_profit(item) {
		if (this.frm.doc.doctype == "Sales Order" && item.valuation_rate) {
			let rate = flt(item.rate) * flt(this.frm.doc.conversion_rate || 1);
			item.gross_profit = flt(((rate - item.valuation_rate) * item.stock_qty), precision("amount", item));
		}
	}

	setup_item_selector() {
		// TODO: remove item selector

		return;
		// if(!this.item_selector) {
		// 	this.item_selector = new erpnext.ItemSelector({frm: this.frm});
		// }
	}

	get_advances() {
		var me = this;
		if(!this.frm.is_return) {
			return this.frm.call({
				method: "set_advances",
				doc: this.frm.doc,
				callback: function(r, rt) {
					refresh_field("advances");
					me.calculate_taxes_and_totals();
				}
			})
		}
	}

	make_payment_entry() {
		return frappe.call({
			method: cur_frm.cscript.get_method_for_payment(),
			args: {
				"dt": cur_frm.doc.doctype,
				"dn": cur_frm.doc.name
			},
			callback: function(r) {
				var doclist = frappe.model.sync(r.message);
				frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				// cur_frm.refresh_fields()
			}
		});
	}

	get_method_for_payment() {
		var method = "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry";
		if(cur_frm.doc.__onload && cur_frm.doc.__onload.make_payment_via_journal_entry){
			if(in_list(['Sales Invoice', 'Purchase Invoice'],  cur_frm.doc.doctype)){
				method = "erpnext.accounts.doctype.journal_entry.journal_entry.get_payment_entry_against_invoice";
			}else {
				method= "erpnext.accounts.doctype.journal_entry.journal_entry.get_payment_entry_against_order";
			}
		}

		return method
	}

	set_query_for_batch(doc, cdt, cdn) {
		// Show item's batches in the dropdown of batch no

		var me = this;
		var item = frappe.get_doc(cdt, cdn);

		if(!item.item_code) {
			frappe.throw(__("Please enter Item Code to get Batch Nos"));
		} else if (doc.doctype == "Purchase Receipt" || doc.doctype == "Purchase Invoice") {
			return {
				filters: {'item': item.item_code}
			}
		} else {
			let filters = {
				'item_code': item.item_code,
				'posting_date': me.frm.doc.posting_date || frappe.datetime.nowdate(),
			}

			if (doc.is_return) {
				filters["is_return"] = 1;
			}

			if (item.warehouse) filters["warehouse"] = item.warehouse;

			return {
				query : "erpnext.controllers.queries.get_batch_no",
				filters: filters
			}
		}
	}

	payment_terms_template() {
		let me = this;
		const doc = this.frm.doc;
		if(doc.payment_terms_template && doc.doctype !== 'Delivery Note') {
			var posting_date = doc.posting_date || doc.transaction_date;
			return frappe.call({
				method: "erpnext.accounts.doctype.payment_terms_template.payment_terms_template.get_payment_terms",
				args: {
					terms_template: doc.payment_terms_template,
					posting_date: posting_date,
					bill_date: doc.bill_date,
					delivery_date: doc.delivery_date || doc.schedule_date,
					grand_total: this.get_payable_amount(),
				},
				callback: function(r) {
					if(r.message && !r.exc) {
						me.frm.set_value("payment_schedule", r.message);
					}
				}
			})
		}
	}

	payment_term(doc, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		if (row.payment_term) {
			frappe.call({
				method: "erpnext.accounts.doctype.payment_terms_template.payment_terms_template.get_payment_term_details",
				args: {
					term: row.payment_term,
					posting_date: this.frm.doc.posting_date || this.frm.doc.transaction_date,
					bill_date: this.frm.doc.bill_date,
					delivery_date: this.frm.doc.delivery_date || this.frm.doc.schedule_date,
					grand_total: this.get_payable_amount(),
				},
				callback: function(r) {
					if (r.message && !r.exc) {
						for (let d in r.message) {
							frappe.model.set_value(cdt, cdn, d, r.message[d]);
						}
					}
				}
			})
		}
	}

	get_payable_amount() {
		let grand_total = flt(this.frm.doc.rounded_total || this.frm.doc.grand_total);

		if (this.frm.doc.write_off_amount) {
			grand_total -= flt(this.frm.doc.write_off_amount);
		}
		if (this.frm.doc.total_advance) {
			grand_total -= flt(this.frm.doc.total_advance);
		}

		return grand_total;
	}

	blanket_order(doc, cdt, cdn) {
		var me = this;
		var item = locals[cdt][cdn];
		if (item.blanket_order && (item.parenttype=="Sales Order" || item.parenttype=="Purchase Order")) {
			frappe.call({
				method: "erpnext.stock.get_item_details.get_blanket_order_details",
				args: {
					args:{
						item_code: item.item_code,
						customer: doc.customer,
						supplier: doc.supplier,
						company: doc.company,
						transaction_date: doc.transaction_date,
						blanket_order: item.blanket_order
					}
				},
				callback: function(r) {
					if (!r.message) {
						frappe.throw(__("Invalid Blanket Order for the selected Customer and Item"));
					} else {
						frappe.run_serially([
							() => frappe.model.set_value(cdt, cdn, "blanket_order_rate", r.message.blanket_order_rate),
							() => me.frm.script_manager.trigger("price_list_rate", cdt, cdn)
						]);
					}
				}
			})
		}
	}

	set_warehouse() {
		erpnext.utils.autofill_warehouse(this.frm.doc.items, "warehouse", this.frm.doc.set_warehouse);
	}

	coupon_code() {
		var me = this;
		frappe.run_serially([
			() => this.frm.doc.ignore_pricing_rule=1,
			() => me.ignore_pricing_rule(),
			() => this.frm.doc.ignore_pricing_rule=0,
			() => me.apply_pricing_rule()
		]);
	}

	add_get_latest_price_button() {
		let me = this;
		me.frm.add_custom_button(__("Get Latest Prices"), function() {
			me.get_latest_price();
		}, __("Prices"));
	}

	add_update_price_list_button() {
		let me = this;
		if (frappe.model.can_create("Item Price")) {
			me.frm.add_custom_button(__("Update Price List"), function () {
				me.update_item_prices();
			}, __("Prices"));
		}
	}
};
