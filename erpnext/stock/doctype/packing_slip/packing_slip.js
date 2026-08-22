frappe.provide("erpnext.stock");

erpnext.stock.PackingSlipController = class PackingSlipController extends erpnext.stock.PackingController {
	item_table_fields = ['items', 'packaging_items']
	calculate_total_hooks = []

	setup() {
		this.frm.custom_make_buttons = {
			'Delivery Note': __('Delivery Note'),
			'Sales Invoice': __('Sales Invoice'),
			'Stock Entry': __('Stock Entry'),
		}

		this.setup_posting_date_time_check();
		this.setup_queries();
	}

	refresh() {
		erpnext.hide_company();
		this.setup_buttons();
	}

	setup_queries() {
		let me = this;

		me.frm.set_query("item_code", "items", function() {
			return erpnext.queries.item({is_stock_item: 1, is_packaging_material: 0});
		});

		me.frm.set_query("item_code", "packaging_items", function() {
			return erpnext.queries.item({is_stock_item: 1});
		});

		me.frm.set_query("subcontracted_item", "items", function() {
			return erpnext.queries.subcontracted_item(me.frm.doc.purchase_order);
		});

		me.setup_warehouse_query();
		erpnext.queries.setup_warehouse_qty_query(me.frm, "source_warehouse", "items");
		erpnext.queries.setup_warehouse_qty_query(me.frm, "source_warehouse", "packaging_items");

		me.frm.set_query("default_rejected_warehouse", () => {
			return erpnext.queries.warehouse(me.frm.doc, (filters) => {
				filters.push(["Warehouse", "stock_type", "=", "Rejected"]);
			});
		});
		me.frm.set_query("rejected_warehouse", "items", () => {
			return erpnext.queries.warehouse(me.frm.doc, (filters) => {
				filters.push(["Warehouse", "stock_type", "=", "Rejected"]);
			});
		});

		const batch_query = (doc, cdt, cdn) => {
			let item = frappe.get_doc(cdt, cdn);
			if (!item.item_code) {
				frappe.throw(__("Please enter Item Code to get Batch Number"));
			} else {
				let filters = {
					item_code: item.item_code,
					warehouse: item.source_warehouse,
					posting_date: me.frm.doc.posting_date || frappe.datetime.nowdate(),
				}

				return {
					query : "erpnext.controllers.queries.get_batch_no",
					filters: filters
				};
			}
		};
		me.frm.set_query("batch_no", "items", batch_query);
		me.frm.set_query("batch_no", "packaging_items", batch_query);

		me.frm.set_query("uom", "items", (doc, cdt, cdn) => {
			let item = frappe.get_doc(cdt, cdn);
			return erpnext.queries.item_uom(item.item_code);
		});
		me.frm.set_query("uom", "packaging_items", (doc, cdt, cdn) => {
			let item = frappe.get_doc(cdt, cdn);
			return erpnext.queries.item_uom(item.item_code);
		});

		me.frm.set_query("customer", erpnext.queries.customer);

		if (me.frm.fields_dict["cost_center"]) {
			me.frm.set_query("cost_center", function(doc) {
				return {
					filters: {
						"company": doc.company,
						"is_group": 0
					}
				};
			});
		}
	}

	setup_buttons() {
		this.add_stock_ledger_report_button();
		this.add_general_ledger_report_button();

		if (this.frm.doc.docstatus == 0) {
			this.frm.add_custom_button(__('Sales Order'), () => {
				this.get_items_from_sales_order();
			}, __("Get Items From"));

			this.frm.add_custom_button(__('Packing Slip'), () => {
				this.get_items_from_packing_slip("Packing Slip");
			}, __("Get Items From"));
		}

		if (this.frm.doc.docstatus == 1 && ["In Stock", "Rejected"].includes(this.frm.doc.status)) {
			if (this.frm.doc.status == "In Stock" && !this.frm.doc.purchase_order) {
				if (this.frm.doc.can_reassign) {
					this.frm.add_custom_button(__('Reassign Sales Order'), () => this.select_sales_order_for_reassignment(),
						__('Reassign'));

					let has_sales_orders = new Set((this.frm.doc.items || []).filter(d => d.sales_order).map(d => d.sales_order));
					if (has_sales_orders.size) {
						this.frm.add_custom_button(__('Unassign Sales Order'), () => this.confirm_unassign_sales_order(),
							__('Reassign'));
					}
				}

				this.frm.add_custom_button(__('Delivery Note'), () => this.make_delivery_note(), __('Create'));
				this.frm.add_custom_button(__('Sales Invoice'), () => this.make_sales_invoice(), __('Create'));
			}

			this.frm.add_custom_button(__('Stock Entry'), () => this.make_stock_entry(), __('Create'));
			this.frm.add_custom_button(__('Unpack'), () => this.make_unpack_packing_slip(), __('Create'));

			if (this.frm.page.get_inner_group_button(__("Create")).length) {
				this.frm.page.set_inner_btn_group_as_primary(__('Create'));
			}
		}

		erpnext.utils.setup_remove_zero_qty_rows(this.frm, ['qty', 'rejected_qty']);
	}

	rejected_qty() {
		this.calculate_totals();
	}

	stock_rejected_qty(doc, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		let calculated_rejected_qty = flt(row.stock_rejected_qty) / (flt(row.conversion_factor) || 1);
		frappe.model.set_value(row.doctype, row.name, "rejected_qty", calculated_rejected_qty);
	}

	gross_weight_per_unit(doc, cdt, cdn) {
		let item = frappe.get_doc(cdt, cdn);
		item.net_weight_per_unit = flt(item.gross_weight_per_unit) - flt(item.tare_weight_per_unit);
		this.calculate_totals();
	}

	gross_weight(doc, cdt, cdn) {
		let item = frappe.get_doc(cdt, cdn);
		if (flt(item.stock_qty)) {
			let new_gross_weight = flt(item.gross_weight) / flt(item.stock_qty);
			frappe.model.set_value(item.doctype, item.name, "gross_weight_per_unit", new_gross_weight);
		} else {
			this.calculate_totals();
		}
	}

	total_gross_weight() {
		if (this.frm.doc.is_unpack) {
			return;
		}
		let has_child_packing_slips = (this.frm.doc.packing_slips || []).length;
		if (has_child_packing_slips) {
			return;
		}

		let unpacked_items = (this.frm.doc.items || []).filter(d => !d.source_packing_slip && flt(d.stock_qty));
		let items_gross_weight = frappe.utils.sum(unpacked_items.map(d => flt(d.gross_weight)));

		let packaging_tare_weight = frappe.utils.sum((this.frm.doc.packaging_items || []).map(d => flt(d.tare_weight)));
		let child_gross_weight = frappe.utils.sum((this.frm.doc.packing_slips || []).map(d => flt(d.gross_weight)));
		let unchangeable_gross_weight = packaging_tare_weight + child_gross_weight;

		let gross_weight_after = flt(this.frm.doc.total_gross_weight, precision("total_gross_weight"));
		let gross_weight_before = flt(unchangeable_gross_weight + items_gross_weight, precision("total_gross_weight"));
		let weight_change = flt(gross_weight_after - gross_weight_before, precision("total_gross_weight"));

		let total_weight_changed = 0;
		for (let [i, row] of unpacked_items.entries()) {
			let row_weight_change = 0;

			if (i == unpacked_items.length - 1) {
				total_weight_changed = flt(total_weight_changed, precision("total_gross_weight"));
				row_weight_change = flt(weight_change - total_weight_changed, precision("gross_weight", row));
			} else {
				row_weight_change = flt(
					weight_change * flt(row.gross_weight) / items_gross_weight,
					precision("gross_weight", row)
				);
			}

			row.net_weight += row_weight_change;
			total_weight_changed += row_weight_change;
			row.net_weight_per_unit = flt(row.net_weight) / flt(row.stock_qty);
		}

		this.calculate_totals();
	}

	calculate_totals() {
		this.frm.doc.total_qty = 0;
		this.frm.doc.total_stock_qty = 0;
		this.frm.doc.total_rejected_qty = 0;
		this.frm.doc.total_stock_rejected_qty = 0;
		this.frm.doc.total_net_weight = 0;
		this.frm.doc.total_tare_weight = 0;

		for (const field of this.item_table_fields) {
			for (let item of this.frm.doc[field] || []) {
				frappe.model.round_floats_in(item, null,
					['net_weight_per_unit', 'tare_weight_per_unit', 'gross_weight_per_unit']);

				if (this.frm.doc.is_unpack || item.source_packing_slip) {
					item.rejected_qty = 0;
				}

				item.stock_qty = flt(item.qty * item.conversion_factor, 6);
				if (frappe.meta.has_field(item.doctype, "rejected_qty")) {
					item.stock_rejected_qty = flt(item.rejected_qty * item.conversion_factor, 6);
				}

				if (frappe.meta.has_field(item.doctype, "net_weight_per_unit")) {
					item.net_weight = flt(item.net_weight_per_unit * item.stock_qty, precision("net_weight", item));
				}
				if (frappe.meta.has_field(item.doctype, "tare_weight_per_unit")) {
					item.tare_weight = flt(item.tare_weight_per_unit * item.stock_qty, precision("tare_weight", item));
				}
				if (frappe.meta.has_field(item.doctype, "gross_weight")) {
					item.gross_weight = flt(item.net_weight + item.tare_weight, precision("gross_weight", item));
					if (item.stock_qty && frappe.meta.has_field(item.doctype, "gross_weight_per_unit")) {
						item.gross_weight_per_unit = item.gross_weight / item.stock_qty;
					}
				}

				if (field == "items") {
					this.frm.doc.total_qty += item.qty;
					this.frm.doc.total_stock_qty += item.stock_qty;
				}

				if (frappe.meta.has_field(item.doctype, "rejected_qty")) {
					this.frm.doc.total_rejected_qty += item.rejected_qty;
					this.frm.doc.total_stock_rejected_qty += item.stock_rejected_qty;
				}

				if (!item.source_packing_slip) {
					this.frm.doc.total_net_weight += flt(item.net_weight);
					this.frm.doc.total_tare_weight += flt(item.tare_weight);
				}
			}
		}

		for (let d of this.frm.doc.packing_slips || []) {
			if (this.frm.doc.is_unpack) {
				this.frm.doc.total_net_weight -= d.net_weight;
				this.frm.doc.total_tare_weight -= d.tare_weight;
			} else {
				this.frm.doc.total_net_weight += d.net_weight;
				this.frm.doc.total_tare_weight += d.tare_weight;
			}
		}

		frappe.model.round_floats_in(this.frm.doc, [
			'total_qty', 'total_stock_qty', 'total_rejected_qty', 'total_stock_rejected_qty', 'total_net_weight', 'total_tare_weight',
		]);
		this.frm.doc.total_gross_weight = flt(this.frm.doc.total_net_weight + this.frm.doc.total_tare_weight,
			precision("total_gross_weight"));

		for (let func of this.calculate_total_hooks || []) {
			func.apply(this);
		}

		this.frm.refresh_fields();
	}

	package_type() {
		this.get_package_type_details();
	}

	get_package_type_details() {
		let me = this;
		if (me.frm.doc.package_type) {
			return frappe.call({
				method: "erpnext.stock.doctype.packing_slip.packing_slip.get_package_type_details",
				args: {
					package_type: me.frm.doc.package_type,
					args: {
						weight_uom: me.frm.doc.weight_uom,
						company: me.frm.doc.company,
						posting_date: me.frm.doc.posting_date,
						doctype: me.frm.doc.doctype,
						name: me.frm.doc.name,
						default_source_warehouse: me.frm.doc.default_source_warehouse,
					}
				},
				callback: function (r) {
					if (r.message && !r.exc) {
						return frappe.run_serially([
							() => {
								if (r.message.weight_uom) {
									return me.frm.set_value("weight_uom", r.message.weight_uom);
								}
							},
							() => {
								me.frm.clear_table("packaging_items");
								if (r.message.packaging_items && r.message.packaging_items.length) {
									for (let d of r.message.packaging_items) {
										me.frm.add_child("packaging_items", d);
									}
								}
								me.calculate_totals();
							}
						]);
					}
				}
			});
		}
	}

	auto_select_batches() {
		return this.frm.call({
			method: 'auto_select_batches',
			doc: this.frm.doc,
			freeze: 1,
			callback: () => {
				this.frm.refresh_fields();
				this.frm.dirty();
			}
		});
	}

	items_remove(doc, cdt, cdn) {
		this.remove_packing_slips_without_items();
		super.items_remove(doc, cdt, cdn);
	}

	packing_slips_remove(doc, cdt, cdn) {
		this.remove_items_without_packing_slips();
		super.packing_slips_remove(doc, cdt, cdn);
	}

	remove_packing_slips_without_items() {
		let contents_packing_slips = (this.frm.doc.items || []).map(d => d.source_packing_slip).filter(d => d);
		contents_packing_slips = [...new Set(contents_packing_slips)];

		let to_remove = [];
		for (let row of this.frm.doc.packing_slips || []) {
			if (!contents_packing_slips.includes(row.source_packing_slip)) {
				to_remove.push(row.source_packing_slip);
			}
		}

		this.frm.doc.packing_slips = (this.frm.doc.packing_slips || []).filter(d => !to_remove.includes(d.source_packing_slip));
		this.frm.doc.packing_slips.forEach((row, index) => (row.idx = index + 1));
		this.frm.refresh_field("packing_slips");
	}

	remove_items_without_packing_slips() {
		let packing_slips = (this.frm.doc.packing_slips || []).map(d => d.source_packing_slip).filter(d => d);

		let to_remove = [];
		for (let row of this.frm.doc.items || []) {
			if (!packing_slips.includes(row.source_packing_slip)) {
				to_remove.push(row.source_packing_slip);
			}
		}

		this.frm.doc.items = (this.frm.doc.items || []).filter(d => !d.source_packing_slip || !to_remove.includes(d.source_packing_slip));
		this.frm.doc.items.forEach((row, index) => (row.idx = index + 1));
		this.frm.refresh_field("items");
	}

	get_items_from_sales_order() {
		erpnext.utils.map_current_doc({
			method: "erpnext.selling.doctype.sales_order.sales_order.make_packing_slip",
			source_doctype: "Sales Order",
			target: this.frm,
			setters: {
				customer: this.frm.doc.customer || undefined,
				project: this.frm.doc.project || undefined,
			},
			columns: ['customer_name', 'project'],
			get_query_filters: {
				docstatus: 1,
				status: ["not in", ["Closed", "On Hold"]],
				delivery_status: "To Deliver",
				packing_status: "To Pack",
				skip_delivery_note: 0,
				company: this.frm.doc.company,
			}
		});
	}

	make_delivery_note() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.packing_slip.packing_slip.make_delivery_note",
			frm: this.frm,
		})
	}

	make_sales_invoice() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.packing_slip.packing_slip.make_sales_invoice",
			frm: this.frm,
		})
	}

	make_unpack_packing_slip() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.packing_slip.packing_slip.make_unpack_packing_slip",
			frm: this.frm,
		})
	}

	make_stock_entry() {
		if (this.frm.doc.purchase_order) {
			return this.make_stock_entry_for_type("Send to Subcontractor");
		} else {
			return this.make_stock_entry_for_type();
		}
	}

	make_stock_entry_for_type(purpose) {
		if (purpose == "Send to Subcontractor") {
			return frappe.call({
				method: "erpnext.buying.doctype.purchase_order.purchase_order.make_rm_stock_entry",
				args: {
					purchase_order: this.frm.doc.purchase_order,
					packing_slips: [this.frm.doc.name],
				},
				callback: function(r) {
					let doclist = frappe.model.sync(r.message);
					frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				}
			});
		} else {
			return frappe.model.open_mapped_doc({
				method: "erpnext.stock.doctype.packing_slip.packing_slip.make_stock_entry",
				frm: this.frm,
			});
		}
	}

	add_stock_ledger_report_button() {
		let me = this;
		if (this.frm.doc.docstatus === 1) {
			this.frm.add_custom_button(__("Stock Ledger"), function() {
				frappe.route_options = {
					packing_slip: me.frm.doc.name,
					from_date: me.frm.doc.posting_date,
					to_date: frappe.datetime.get_today(),
					company: me.frm.doc.company,
					group_by: ""
				};
				frappe.set_route("query-report", "Stock Ledger");
			}, __("View"));
		}
	}

	select_sales_order_for_reassignment() {
		let msd = new frappe.ui.form.MultiSelectDialog({
			doctype: "Sales Order",
			date_field: "transaction_date",
			single_selection: true,
			primary_action_label: __("Reassign"),
			setters: [
				{
					fieldtype: 'Link',
					label: __('Customer'),
					options: 'Customer',
					fieldname: 'customer',
				},
				{
					fieldtype: 'Link',
					label: __('Project'),
					options: 'Project',
					fieldname: 'project',
					default: this.frm.doc.project || undefined,
				},
				{
					fieldtype: 'Link',
					label: __('Branch'),
					options: 'Branch',
					fieldname: 'branch',
					default: this.frm.doc.branch || undefined,
				},
				{
					fieldtype: 'DateRange',
					label: __('Date Range'),
					fieldname: 'transaction_date',
				}
			],
			columns: ['customer_name', 'transaction_date', 'project'],
			get_query: () => {
				return {
					query: "erpnext.stock.doctype.packing_slip.packing_slip.get_sales_orders_for_reassignment",
					filters: {
						packing_slip: this.frm.doc.name,
					}
				};
			},
			action: (selections, args) => {
				if (selections.length != 1) {
					frappe.msgprint(__("Please select one {0}", [__("Sales Order")]))
					return;
				}

				this.reassign_sales_order(selections[0]);
				msd.dialog.hide();
			},
		});
	}

	confirm_unassign_sales_order() {
		return frappe.confirm(__("Are you sure you want to unassign Sales Orders from this Package?"), () => {
			return this.reassign_sales_order(null);
		});
	}

	reassign_sales_order(sales_order) {
		return frappe.call({
			method: "erpnext.stock.doctype.packing_slip.packing_slip.reassign_sales_order",
			args: {
				packing_slip: this.frm.doc.name,
				sales_order: sales_order,
			},
			freeze: 1,
			freeze_message: __("Reassigning..."),
			callback: (r) => {
				this.frm.reload_doc();
			}
		});
	}
};

extend_cscript(cur_frm.cscript, new erpnext.stock.PackingSlipController({frm: cur_frm}));
