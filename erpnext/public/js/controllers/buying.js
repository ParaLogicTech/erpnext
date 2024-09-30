// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext.buying");

cur_frm.cscript.tax_table = "Purchase Taxes and Charges";

{% include 'erpnext/accounts/doctype/purchase_taxes_and_charges_template/purchase_taxes_and_charges_template.js' %}

cur_frm.email_field = "contact_email";

erpnext.buying.BuyingController = class BuyingController extends erpnext.TransactionController {
	setup() {
		super.setup();

		frappe.ui.form.on(this.frm.doctype + " Item", {
			items_add: function(frm, cdt, cdn) {
				var item = frappe.get_doc(cdt, cdn);
				if(!item.project && frm.doc.project) {
					item.project = frm.doc.project;
				}
			}
		});

		frappe.ui.form.on(this.frm.doctype, {
			project: function(frm) {
				var me = this;
				if (frm.doc.project) {
					$.each(frm.doc.items || [], function (i, item) {
						frappe.model.set_value(frm.doctype + " Item", item.name, "project", frm.doc.project);
					});
				}
			}
		});
	}

	onload(doc, cdt, cdn) {
		this.setup_queries(doc, cdt, cdn);
		super.onload();

		this.frm.set_query('shipping_rule', function() {
			return {
				filters: {
					"shipping_rule_type": "Buying"
				}
			};
		});

		if (this.frm.doc.__islocal
			&& frappe.meta.has_field(this.frm.doc.doctype, "disable_rounded_total")) {

				var df = frappe.meta.get_docfield(this.frm.doc.doctype, "disable_rounded_total");
				var disable = cint(df.default) || cint(frappe.sys_defaults.disable_rounded_total);
				this.frm.set_value("disable_rounded_total", disable);
		}

		/* eslint-disable */
		// no idea where me is coming from
		if(this.frm.get_field('shipping_address')) {
			this.frm.set_query("shipping_address", function() {
				if(me.frm.doc.customer) {
					return {
						query: 'frappe.contacts.doctype.address.address.address_query',
						filters: { link_doctype: 'Customer', link_name: me.frm.doc.customer }
					};
				} else
					return erpnext.queries.company_address_query(me.frm.doc)
			});
		}
		/* eslint-enable */
	}

	setup_queries(doc, cdt, cdn) {
		var me = this;

		if(this.frm.fields_dict.buying_price_list) {
			this.frm.set_query("buying_price_list", function() {
				return{
					filters: { 'buying': 1 }
				}
			});
		}

		if(this.frm.fields_dict.tc_name) {
			this.frm.set_query("tc_name", function() {
				return{
					filters: { 'buying': 1 }
				}
			});
		}

		if(this.frm.fields_dict.transaction_type) {
			this.frm.set_query("transaction_type", function() {
				return{
					filters: { 'buying': 1 }
				}
			});
		}

		me.frm.set_query('supplier', erpnext.queries.supplier);
		me.frm.set_query('contact_person', erpnext.queries.contact_query);
		me.frm.set_query('supplier_address', erpnext.queries.address_query);

		if(this.frm.fields_dict.supplier) {
			this.frm.set_query("supplier", function() {
				return{	query: "erpnext.controllers.queries.supplier_query" }});
		}

		this.frm.set_query("item_code", "items", function(doc) {
			var filters = {};

			if (me.frm.doc.is_subcontracted) {
				filters['is_sub_contracted_item'] = 1;
			} else {
				filters['is_purchase_item'] = 1;
			}

			return {
				query: "erpnext.controllers.queries.item_query",
				filters: filters
			}
		});

		if(this.frm.fields_dict["items"].grid.get_field('vehicle')) {
			this.frm.set_query("vehicle", "items", function(doc, cdt, cdn) {
				var item = frappe.get_doc(cdt, cdn);

				var filters = {};
				if (item.item_code) {
					filters.item_code = item.item_code;
				}

				if (doc.doctype === "Purchase Receipt" || (doc.doctype === "Purchase Invoice" && doc.update_stock)) {
					if (doc.is_return) {
						if (item.warehouse) {
							filters['warehouse'] = item.warehouse;
						} else {
							filters['warehouse'] = ['is', 'set'];
						}
					} else {
						filters['warehouse'] = ['is', 'not set'];
						filters['purchase_document_no'] = ['is', 'not set'];
					}
				}

				if (doc.doctype === "Purchase Invoice" && item.purchase_receipt) {
					filters['purchase_document_type'] = 'Purchase Receipt';
					filters['purchase_document_no'] = item.purchase_receipt;
				}
				return {
					filters: filters
				}
			});
		}


		this.frm.set_query("manufacturer", "items", function(doc, cdt, cdn) {
			const row = locals[cdt][cdn];
			return {
				query: "erpnext.controllers.queries.item_manufacturer_query",
				filters:{ 'item_code': row.item_code }
			}
		});
	}

	refresh(doc) {
		frappe.dynamic_link = {doc: this.frm.doc, fieldname: 'supplier', doctype: 'Supplier'};
		super.refresh();
	}

	supplier() {
		var me = this;
		return erpnext.utils.get_party_details(this.frm, null, null, function(){
			me.apply_price_list();
		});
	}

	supplier_address() {
		erpnext.utils.get_address_display(this.frm);
		erpnext.utils.set_taxes_from_address(this.frm, "supplier_address", "supplier_address", "supplier_address");
	}

	buying_price_list() {
		this.apply_price_list();
	}

	price_list_rate(doc, cdt, cdn) {
		var item = frappe.get_doc(cdt, cdn);

		let item_rate = item.price_list_rate;
		if (doc.doctype == "Purchase Order" && item.blanket_order_rate) {
			item_rate = item.blanket_order_rate;
		}

		if (item.discount_percentage) {
			item.discount_amount = flt(item_rate) * flt(item.discount_percentage) / 100;
		} else if (flt(item.price_list_rate)) {
			item.discount_percentage = flt(item.discount_amount) / flt(item.price_list_rate) * 100;
		}

		if (item.discount_amount) {
			item.rate = flt((item.price_list_rate) - (item.discount_amount));
		} else {
			item.rate = item_rate;
		}

		this.calculate_taxes_and_totals();
	}

	discount_percentage(doc, cdt, cdn) {
		var item = frappe.get_doc(cdt, cdn);
		item.discount_amount = 0.0;
		this.price_list_rate(doc, cdt, cdn);
	}

	discount_amount(doc, cdt, cdn) {
		var item = frappe.get_doc(cdt, cdn);
		item.discount_percentage = 0.0;
		this.price_list_rate(doc, cdt, cdn);
	}

	qty(doc, cdt, cdn) {
		let item = frappe.get_doc(cdt, cdn);
		if (
			(doc.doctype == "Purchase Receipt")
			|| (doc.doctype == "Purchase Invoice" && (doc.update_stock || doc.is_return))
		) {
			frappe.model.round_floats_in(item, ["qty", "received_qty"]);

			if (!doc.is_return && this.validate_negative_quantity(cdt, cdn, item, ["qty", "received_qty"])) {
				return;
			}

			if (!item.rejected_qty && item.qty) {
				item.received_qty = item.qty;
			}

			frappe.model.round_floats_in(item, ["qty", "received_qty"]);
			item.rejected_qty = flt(item.received_qty - item.qty, precision("rejected_qty", item));
		}

		super.qty(doc, cdt, cdn);
	}

	received_qty(doc, cdt, cdn) {
		this.calculate_accepted_qty(doc, cdt, cdn)
	}

	rejected_qty(doc, cdt, cdn) {
		this.calculate_accepted_qty(doc, cdt, cdn)
	}

	calculate_accepted_qty(doc, cdt, cdn) {
		let item = frappe.get_doc(cdt, cdn);
		frappe.model.round_floats_in(item, ["received_qty", "rejected_qty"]);

		if (!doc.is_return && this.validate_negative_quantity(cdt, cdn, item, ["received_qty", "rejected_qty"])) {
			return;
		}

		item.qty = flt(item.received_qty - item.rejected_qty, precision("qty", item));
		this.qty(doc, cdt, cdn);
	}

	validate_negative_quantity(cdt, cdn, item, fieldnames) {
		if(!item || !fieldnames) { return }

		var is_negative_qty = false;
		for(var i = 0; i<fieldnames.length; i++) {
			if(item[fieldnames[i]] < 0){
				frappe.msgprint(__("Row #{0}: {1} can not be negative for item {2}",
					[item.idx,__(frappe.meta.get_label(cdt, fieldnames[i], cdn)), item.item_code]));
				is_negative_qty = true;
				break;
			}
		}

		return is_negative_qty
	}

	warehouse(doc, cdt, cdn) {
		var item = frappe.get_doc(cdt, cdn);
		if(item.item_code && item.warehouse) {
			return this.frm.call({
				method: "erpnext.stock.get_item_details.get_bin_details",
				child: item,
				args: {
					item_code: item.item_code,
					warehouse: item.warehouse
				}
			});
		}
	}

	rejected_warehouse(doc, cdt) {
		if (["Purchase Invoice", "Purchase Receipt"].includes(cdt)) {
			erpnext.utils.autofill_warehouse(doc.items, "rejected_warehouse", doc.rejected_warehouse, true);
		}
	}

	set_reserve_warehouse() {
		erpnext.utils.autofill_warehouse(this.frm.doc.supplied_items, "reserve_warehouse", this.frm.doc.set_reserve_warehouse);
	}

	category(doc, cdt, cdn) {
		// should be the category field of tax table
		if(cdt != doc.doctype) {
			this.calculate_taxes_and_totals();
		}
	}
	add_deduct_tax(doc, cdt, cdn) {
		this.calculate_taxes_and_totals();
	}

	set_from_product_bundle() {
		let me = this;

		if (frappe.model.can_read("Product Bundle")) {
			this.frm.add_custom_button(__("Product Bundle"), function () {
				erpnext.buying.get_items_from_product_bundle(me.frm);
			}, __("Get Items From"));
		}
	}

	shipping_address() {
		var me = this;
		erpnext.utils.get_address_display(this.frm, "shipping_address",
			"shipping_address_display", true);
	}

	pol_address() {
		erpnext.utils.get_address_display(this.frm, "pol_address",
			"pol_address_display");
	}
	poa_address() {
		erpnext.utils.get_address_display(this.frm, "poa_address",
			"poa_address_display");
	}

	tc_name() {
		this.get_terms();
	}

	make_landed_cost_voucher() {
		return frappe.call({
			method: "erpnext.stock.doctype.landed_cost_voucher.landed_cost_voucher.get_landed_cost_voucher",
			args: {
				"dt": cur_frm.doc.doctype,
				"dn": cur_frm.doc.name
			},
			callback: function(r) {
				var doclist = frappe.model.sync(r.message);
				frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
			}
		});
	}

	link_to_mrs() {
		var my_items = [];
		for (var i in cur_frm.doc.items) {
			if(!cur_frm.doc.items[i].material_request){
				my_items.push(cur_frm.doc.items[i].item_code);
			}
		}
		frappe.call({
			method: "erpnext.buying.utils.get_linked_material_requests",
			args:{
				items: my_items
			},
			callback: function(r) {
				if(!r.message || r.message.length == 0) {
					frappe.throw(__("No pending Material Requests found to link for the given items."))
				}
				else {
					var i = 0;
					var item_length = cur_frm.doc.items.length;
					while (i < item_length) {
						var qty = cur_frm.doc.items[i].qty;
						(r.message[0] || []).forEach(function(d) {
							if (d.qty > 0 && qty > 0 && cur_frm.doc.items[i].item_code == d.item_code && !cur_frm.doc.items[i].material_request_item)
							{
								cur_frm.doc.items[i].material_request = d.mr_name;
								cur_frm.doc.items[i].material_request_item = d.mr_item;
								var my_qty = Math.min(qty, d.qty);
								qty = qty - my_qty;
								d.qty = d.qty  - my_qty;
								cur_frm.doc.items[i].stock_qty = my_qty*cur_frm.doc.items[i].conversion_factor;
								cur_frm.doc.items[i].qty = my_qty;

								frappe.msgprint("Assigning " + d.mr_name + " to " + d.item_code + " (row " + cur_frm.doc.items[i].idx + ")");
								if (qty > 0)
								{
									frappe.msgprint("Splitting " + qty + " units of " + d.item_code);
									var newrow = frappe.model.add_child(cur_frm.doc, cur_frm.doc.items[i].doctype, "items");
									item_length++;

									for (var key in cur_frm.doc.items[i])
									{
										newrow[key] = cur_frm.doc.items[i][key];
									}

									newrow.idx = item_length;
									newrow["stock_qty"] = newrow.conversion_factor*qty;
									newrow["qty"] = qty;

									newrow["material_request"] = "";
									newrow["material_request_item"] = "";

								}
							}
						});
						i++;
					}
					refresh_field("items");
					//cur_frm.save();
				}
			}
		});
	}

	update_auto_repeat_reference(doc) {
		if (doc.auto_repeat) {
			frappe.call({
				method:"frappe.automation.doctype.auto_repeat.auto_repeat.update_reference",
				args:{
					docname: doc.auto_repeat,
					reference:doc.name
				},
				callback: function(r){
					if (r.message=="success") {
						frappe.show_alert({message:__("Auto repeat document updated"), indicator:'green'});
					} else {
						frappe.show_alert({message:__("An error occurred during the update process"), indicator:'red'});
					}
				}
			})
		}
	}

	manufacturer(doc, cdt, cdn) {
		const row = locals[cdt][cdn];

		if(row.manufacturer) {
			frappe.call({
				method: "erpnext.stock.doctype.item_manufacturer.item_manufacturer.get_item_manufacturer_part_no",
				args: {
					'item_code': row.item_code,
					'manufacturer': row.manufacturer
				},
				callback: function(r) {
					if (r.message) {
						frappe.model.set_value(cdt, cdn, 'manufacturer_part_no', r.message);
					}
				}
			});
		}
	}

	manufacturer_part_no(doc, cdt, cdn) {
		const row = locals[cdt][cdn];

		if (row.manufacturer_part_no) {
			frappe.model.get_value('Item Manufacturer',
				{
					'item_code': row.item_code,
					'manufacturer': row.manufacturer,
					'manufacturer_part_no': row.manufacturer_part_no
				},
				'name',
				function(data) {
					if (!data) {
						let msg = {
							message: __("Manufacturer Part Number <b>{0}</b> is invalid", [row.manufacturer_part_no]),
							title: __("Invalid Part Number")
						}
						frappe.throw(msg);
					}
				});

			}
		}
};

erpnext.buying.get_default_bom = function(frm) {
	$.each(frm.doc["items"] || [], function(i, d) {
		if (d.item_code && !d.bom) {
			return frappe.call({
				type: "GET",
				method: "erpnext.stock.get_item_details.get_default_bom",
				args: {
					"item_code": d.item_code,
				},
				callback: function(r) {
					if(r) {
						frappe.model.set_value(d.doctype, d.name, "bom", r.message);
					}
				}
			})
		}
	});
}

erpnext.buying.set_default_supplier_warehouse = function(frm) {
	if (frm.doc.is_subcontracted && !frm.doc.supplier_warehouse && frm.fields_dict.supplier_warehouse) {
		let default_supplier_warehouse = frappe.defaults.get_default("default_subcontracting_supplier_warehouse");
		if (default_supplier_warehouse) {
			frm.set_value("supplier_warehouse", default_supplier_warehouse);
		}
	}
}

erpnext.buying.get_items_from_product_bundle = function(frm) {
	var dialog = new frappe.ui.Dialog({
		title: __("Get Items from Product Bundle"),
		fields: [
			{
				"fieldtype": "Link",
				"label": __("Product Bundle"),
				"fieldname": "product_bundle",
				"options":"Product Bundle",
				"reqd": 1
			},
			{
				"fieldtype": "Currency",
				"label": __("Quantity"),
				"fieldname": "quantity",
				"reqd": 1,
				"default": 1
			},
			{
				"fieldtype": "Button",
				"label": __("Get Items"),
				"fieldname": "get_items",
				"cssClass": "btn-primary"
			}
		]
	});

	dialog.fields_dict.get_items.$input.click(function() {
		var args = dialog.get_values();
		if(!args) return;
		dialog.hide();
		return frappe.call({
			type: "GET",
			method: "erpnext.stock.doctype.packed_item.packed_item.get_items_from_product_bundle",
			args: {
				args: {
					item_code: args.product_bundle,
					quantity: args.quantity,
					parenttype: frm.doc.doctype,
					parent: frm.doc.name,
					supplier: frm.doc.supplier,
					currency: frm.doc.currency,
					conversion_rate: frm.doc.conversion_rate,
					price_list: frm.doc.buying_price_list,
					price_list_currency: frm.doc.price_list_currency,
					plc_conversion_rate: frm.doc.plc_conversion_rate,
					company: frm.doc.company,
					is_subcontracted: frm.doc.is_subcontracted,
					transaction_date: frm.doc.transaction_date || frm.doc.posting_date,
					ignore_pricing_rule: frm.doc.ignore_pricing_rule,
					doctype: frm.doc.doctype
				}
			},
			freeze: true,
			callback: function(r) {
				const first_row_is_empty = function(child_table){
					if($.isArray(child_table) && child_table.length > 0) {
						return !child_table[0].item_code;
					}
					return false;
				};

				const remove_empty_first_row = function(frm){
				if (first_row_is_empty(frm.doc.items)){
					frm.doc.items = frm.doc.items.splice(1);
					}
				};

				if(!r.exc && r.message) {
					remove_empty_first_row(frm);
					for ( var i=0; i< r.message.length; i++ ) {
						var d = frm.add_child("items");
						var item = r.message[i];
						for ( var key in  item) {
							if ( !is_null(item[key]) && key !== "doctype" ) {
								d[key] = item[key];
							}
						}
						if(frappe.meta.get_docfield(d.doctype, "price_list_rate", d.name)) {
							frm.script_manager.trigger("price_list_rate", d.doctype, d.name);
						}
					}
					frm.refresh_field("items");
				}
			}
		})
	});
	dialog.show();
}
