// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

{% include 'erpnext/public/js/controllers/buying.js' %};

frappe.provide("erpnext.stock");

frappe.ui.form.on("Purchase Receipt", {
	setup: (frm) => {
		frm.make_methods = {
			'Landed Cost Voucher': () => {
				let lcv = frappe.model.get_new_doc('Landed Cost Voucher');
				lcv.company = frm.doc.company;

				let lcv_receipt = frappe.model.get_new_doc('Landed Cost Purchase Receipt');
				lcv_receipt.receipt_document_type = 'Purchase Receipt';
				lcv_receipt.receipt_document = frm.doc.name;
				lcv_receipt.supplier = frm.doc.supplier;
				lcv_receipt.grand_total = frm.doc.grand_total;
				lcv.purchase_receipts = [lcv_receipt];

				frappe.set_route("Form", lcv.doctype, lcv.name);
			},
		}
		
		frm.custom_make_buttons = {
			'Purchase Receipt': 'Purchase Return',
			'Purchase Invoice': 'Purchase Invoice',
			'Landed Cost Voucher': 'Landed Cost Voucher',
			'Auto Repeat': 'Subscription',
		}

		frm.set_query("expense_account", "items", function() {
			return {
				query: "erpnext.controllers.queries.get_expense_account",
				filters: {'company': frm.doc.company }
			}
		});
		
	},
	onload: function(frm) {
		erpnext.queries.setup_queries(frm, "Warehouse", function() {
			return erpnext.queries.warehouse(frm.doc);
		});
	},

	refresh: function(frm) {
		if(frm.doc.company) {
			frm.trigger("toggle_display_account_head");
		}

		if (
			frm.doc.docstatus === 1
			&& frm.doc.is_return === 1
			&& frm.doc.billing_status == "To Bill"
			&& frappe.model.can_create("Purchase Invoice")
		) {
			frm.add_custom_button(__('Debit Note'), function() {
				frappe.model.open_mapped_doc({
					method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice",
					frm: cur_frm,
				})
			}, __('Create'));
			frm.page.set_inner_btn_group_as_primary(__('Create'));
		}

		frm.set_indicator_formatter('item_code', function(doc) {
			if (doc.docstatus === 0) {
				if (!doc.is_stock_item) {
					return "blue";
				}
			} else if (doc.docstatus === 1) {
				var completed_qty = flt(doc.billed_qty) + flt(doc.returned_qty);
				if (!completed_qty) {
					return "orange";
				} else if (doc.returned_qty >= doc.qty) {
					return "grey";
				} else if (completed_qty < doc.qty) {
					return "yellow";
				} else if (doc.billed_qty < doc.qty) {
					return "blue";
				} else {
					return "green";
				}
			}
		});
	},

	company: function(frm) {
		frm.trigger("toggle_display_account_head");
	},

	toggle_display_account_head: function(frm) {
		var enabled = erpnext.is_perpetual_inventory_enabled(frm.doc.company)
		frm.fields_dict["items"].grid.set_column_disp(["cost_center"], enabled);
	}
});

erpnext.stock.PurchaseReceiptController = class PurchaseReceiptController extends erpnext.buying.BuyingController {
	setup(doc) {
		this.setup_posting_date_time_check();
		super.setup(doc);
	}

	refresh() {
		let me = this;
		super.refresh();
		if(this.frm.doc.docstatus===1) {
			this.show_stock_ledger();
			//removed for temporary
			this.show_general_ledger();

			if (frappe.model.can_read("Asset")) {
				this.frm.add_custom_button(__('Asset'), function () {
					frappe.route_options = {
						purchase_receipt: me.frm.doc.name,
					};
					frappe.set_route("List", "Asset");
				}, __("View"));

				this.frm.add_custom_button(__('Asset Movement'), function () {
					frappe.route_options = {
						reference_name: me.frm.doc.name,
					};
					frappe.set_route("List", "Asset Movement");
				}, __("View"));
			}
		}

		if (me.frm.doc.docstatus == 0) {
			me.add_get_latest_price_button();
		}
		if (me.frm.doc.docstatus == 1) {
			me.add_update_price_list_button();
		}

		if(!this.frm.doc.is_return && this.frm.doc.status != "Closed") {
			if (this.frm.doc.docstatus == 0 && frappe.model.can_read("Purchase Order")) {
				this.frm.add_custom_button(__('Purchase Order'), function () {
					erpnext.utils.map_current_doc({
						method: "erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt",
						source_doctype: "Purchase Order",
						target: me.frm,
						setters: [
							{
								fieldtype: 'Link',
								label: __('Supplier'),
								options: 'Supplier',
								fieldname: 'supplier',
								default: me.frm.doc.supplier || undefined,
							},
							{
								fieldtype: 'DateRange',
								label: __('Date Range'),
								fieldname: 'transaction_date',
							}
						],
						columns: ['supplier_name', 'transaction_date'],
						get_query_filters: {
							supplier: me.frm.doc.supplier || undefined,
							docstatus: 1,
							status: ["not in", ["Closed", "On Hold"]],
							receipt_status: "To Receive",
							company: me.frm.doc.company
						}
					});
				}, __("Get Items From"));
			}

			if (this.frm.doc.docstatus == 1 && this.frm.doc.status != "Closed") {
				if (this.frm.has_perm("submit")) {
					me.frm.add_custom_button(__("Close"), this.close_purchase_receipt,
						__("Status"))
				}

				if(flt(this.frm.doc.per_completed) < 100 && frappe.model.can_create("Purchase Invoice")) {
					me.frm.add_custom_button(__('Purchase Invoice'), this.make_purchase_invoice,
						__('Create'));
				}

				if (frappe.model.can_create("Purchase Receipt")) {
					me.frm.add_custom_button(__('Purchase Return'), this.make_purchase_return,
						__('Create'));
				}

				if (frappe.model.can_create("Landed Cost Voucher")) {
					me.frm.add_custom_button(__('Landed Cost Voucher'), this.make_landed_cost_voucher,
						__("Create"));
				}

				if (frappe.model.can_create("Stock Entry")) {
					me.frm.add_custom_button(__('Make Material Transfer'), cur_frm.cscript['Make Stock Entry'],
						__('Create'));

					me.frm.add_custom_button(__('Retention Stock Entry'), this.make_retention_stock_entry,
						__('Create'));
				}

				if(!this.frm.doc.auto_repeat && frappe.model.can_create("Auto Repeat")) {
					me.frm.add_custom_button(__('Subscription'), function() {
						erpnext.utils.make_subscription(me.frm.doc.doctype, me.frm.doc.name)
					}, __('Create'))
				}

				me.frm.page.set_inner_btn_group_as_primary(__('Create'));
			}
		}

		if (me.frm.doc.docstatus === 1 && me.frm.doc.status != "Closed" && !me.frm.doc.inter_company_reference) {
			if (me.frm.doc.__onload?.is_internal_supplier) {
				me.frm.add_custom_button("Inter Company Delivery", function() {
					me.make_inter_company_delivery(me.frm);
				}, __('Create'));
			}
		}

		if (this.frm.doc.docstatus==1 && this.frm.doc.status === "Closed" && this.frm.has_perm("submit")) {
			me.frm.add_custom_button(__('Re-Open'), this.reopen_purchase_receipt,
				__("Status"))
		}
	}

	make_purchase_invoice() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice",
			frm: cur_frm
		})
	}

	make_purchase_return() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return",
			frm: cur_frm
		})
	}

	make_inter_company_delivery() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_inter_company_delivery_note",
			frm: this.frm
		});
	}

	close_purchase_receipt() {
		cur_frm.cscript.update_status("Closed");
	}

	reopen_purchase_receipt() {
		cur_frm.cscript.update_status("Submitted");
	}

	make_retention_stock_entry() {
		frappe.call({
			method: "erpnext.stock.doctype.stock_entry.stock_entry.move_sample_to_retention_warehouse",
			args:{
				"company": cur_frm.doc.company,
				"items": cur_frm.doc.items
			},
			callback: function (r) {
				if (r.message) {
					var doc = frappe.model.sync(r.message)[0];
					frappe.set_route("Form", doc.doctype, doc.name);
				}
				else {
					frappe.msgprint(__("Purchase Receipt doesn't have any Item for which Retain Sample is enabled."));
				}
			}
		});
	}

};

// for backward compatibility: combine new and previous states
extend_cscript(cur_frm.cscript, new erpnext.stock.PurchaseReceiptController({frm: cur_frm}));

cur_frm.cscript.update_status = function(status) {
	frappe.ui.form.is_saving = true;
	frappe.call({
		method:"erpnext.stock.doctype.purchase_receipt.purchase_receipt.update_purchase_receipt_status",
		args: {docname: cur_frm.doc.name, status: status},
		callback: function(r){
			if(!r.exc)
				cur_frm.reload_doc();
		},
		always: function(){
			frappe.ui.form.is_saving = false;
		}
	})
}

cur_frm.fields_dict['items'].grid.get_field('project').get_query = function(doc, cdt, cdn) {
	return {
		filters: [
			['Project', 'status', 'not in', 'Completed, Cancelled']
		]
	}
}

cur_frm.fields_dict['select_print_heading'].get_query = function(doc, cdt, cdn) {
	return {
		filters: [
			['Print Heading', 'docstatus', '!=', '2']
		]
	}
}

cur_frm.fields_dict['items'].grid.get_field('bom').get_query = function(doc, cdt, cdn) {
	var d = locals[cdt][cdn]
	return {
		filters: [
			['BOM', 'item', '=', d.item_code],
			['BOM', 'is_active', '=', '1'],
			['BOM', 'docstatus', '=', '1']
		]
	}
}

frappe.provide("erpnext.buying");

frappe.ui.form.on("Purchase Receipt", "is_subcontracted", function(frm) {
	if (frm.doc.is_subcontracted) {
		erpnext.buying.get_default_bom(frm);
	}
});

frappe.ui.form.on('Purchase Receipt Item', {
	item_code: function(frm, cdt, cdn) {
		var d = locals[cdt][cdn];
		frappe.db.get_value('Item', {name: d.item_code}, 'sample_quantity', (r) => {
			frappe.model.set_value(cdt, cdn, "sample_quantity", r.sample_quantity);
			validate_sample_quantity(frm, cdt, cdn);
		});
	},
	qty: function(frm, cdt, cdn) {
		validate_sample_quantity(frm, cdt, cdn);
	},
	sample_quantity: function(frm, cdt, cdn) {
		validate_sample_quantity(frm, cdt, cdn);
	},
	batch_no: function(frm, cdt, cdn) {
		validate_sample_quantity(frm, cdt, cdn);
	},
});

cur_frm.cscript['Make Stock Entry'] = function() {
	frappe.model.open_mapped_doc({
		method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_stock_entry",
		frm: cur_frm,
	})
}

var validate_sample_quantity = function(frm, cdt, cdn) {
	var d = locals[cdt][cdn];
	if (d.sample_quantity && d.qty) {
		frappe.call({
			method: 'erpnext.stock.doctype.stock_entry.stock_entry.validate_sample_quantity',
			args: {
				batch_no: d.batch_no,
				item_code: d.item_code,
				sample_quantity: d.sample_quantity,
				qty: d.qty
			},
			callback: (r) => {
				frappe.model.set_value(cdt, cdn, "sample_quantity", r.message);
			}
		});
	}
};
