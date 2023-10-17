frappe.provide("erpnext.manufacturing");

erpnext.manufacturing.work_order_qty_prompt_hooks = [];
erpnext.manufacturing.multiple_work_orders_qty_prompt_hooks = [];

$.extend(erpnext.manufacturing, {
	make_stock_entry: function(doc, purpose) {
		if (doc.docstatus != 1) {
			return;
		}

		return erpnext.manufacturing.show_prompt_for_qty_input(doc, purpose).then(r => {
			return frappe.call({
				method: "erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry",
				args: {
					"work_order_id": doc.name,
					"purpose": purpose,
					"scrap_remaining": r.data.scrap_remaining,
					"qty": r.data.qty,
					"args": r.args,
				},
				freeze: 1,
				callback: (r) => {
					if (r.message) {
						frappe.model.sync(r.message);

						if (cur_frm && cur_frm.doc.doctype == "Work Order" && cur_frm.doc.name == doc.name) {
							cur_frm.reload_doc();
						}

						if (r.message.docstatus != 1) {
							frappe.set_route('Form', r.message.doctype, r.message.name);
						}
					}
				}
			});
		});
	},

	show_prompt_for_qty_input: function(doc, purpose) {
		return new Promise((resolve, reject) => {
			frappe.model.with_doctype("Work Order", () => {
				let [max, max_with_allowance] = erpnext.manufacturing.get_max_transferable_qty(doc, purpose);

				let fields = [
					{
						fieldtype: 'Float',
						label: __('Qty for {0}', [purpose]),
						fieldname: 'qty',
						description: __('Max: {0}', [format_number(max)]),
						reqd: 1,
						default: max
					}
				];

				if (purpose === "Manufacture" && frappe.defaults.get_default('scrap_remaining_by_default')) {
					fields.push({
						fieldtype: 'Check',
						label: __('Scrap Remaining'),
						fieldname: 'scrap_remaining',
						default: cint(frappe.defaults.get_default('scrap_remaining_by_default')),
					})
				}

				fields = fields.concat([
					{
						fieldtype: 'Section Break',
					},
					{
						label: __('Qty to Produce'),
						fieldname: 'qty_to_produce',
						fieldtype: 'Float',
						default: flt(doc.qty),
						read_only: 1,
					},
				]);

				if (doc.max_qty) {
					fields = fields.concat([
						{
							fieldtype: 'Column Break',
						},
						{
							label: __('Maximum Qty'),
							fieldname: 'max_qty',
							fieldtype: 'Float',
							default: flt(doc.max_qty),
							read_only: 1,
						},
					]);
				}

				fields = fields.concat([
					{
						fieldtype: 'Column Break',
					},
					{
						label: __('Produced Qty'),
						fieldname: 'produced_qty',
						fieldtype: 'Float',
						default: flt(doc.produced_qty),
						read_only: 1,
					},
				]);

				if (!doc.skip_transfer) {
					fields = fields.concat([
						{
							fieldtype: 'Column Break',
						},
						{
							label: __('Transferred Qty'),
							fieldname: 'transferred_qty',
							fieldtype: 'Float',
							default: flt(doc.material_transferred_for_manufacturing),
							read_only: 1,
						},
					]);
				}

				fields = fields.concat([
					{
						fieldtype: 'Section Break',
					},
					{
						label: __('Work Order'),
						fieldname: 'work_order',
						fieldtype: 'Link',
						options: "Work Order",
						default: doc.name,
						read_only: 1,
					},
					{
						label: __('Production Item'),
						fieldname: 'production_item',
						fieldtype: 'Link',
						options: "Item",
						default: doc.production_item,
						read_only: 1,
					},
					{
						label: __('Production Item Name'),
						fieldname: 'production_item_name',
						fieldtype: 'Data',
						default: doc.item_name,
						read_only: 1,
					},
				]);

				for (let hook of erpnext.manufacturing.work_order_qty_prompt_hooks || []) {
					hook(doc, purpose, fields);
				}

				frappe.prompt(fields, data => {
					if (flt(data.qty) > max_with_allowance) {
						frappe.msgprint(__('Quantity can not be more than {0}', [format_number(max_with_allowance)]));
						reject();
					}

					let send_to_stock_entry_fieldnames = fields.filter(f => f.send_to_stock_entry).map(f => f.fieldname);
					let stock_entry_args = {};
					for (let fieldname of send_to_stock_entry_fieldnames) {
						if (data[fieldname]) {
							stock_entry_args[fieldname] = data[fieldname];
						}
					}

					data.purpose = purpose;
					resolve({
						data: data,
						args: stock_entry_args,
					});
				}, __(purpose), __('Submit'));
			});
		});
	},

	finish_multiple_work_orders: function(work_orders) {
		this.show_qty_prompt_for_multiple_work_orders(work_orders).then(r => {
			return frappe.call({
				method: "erpnext.manufacturing.doctype.work_order.work_order.finish_multiple_work_orders",
				args: {
					work_orders: r.work_orders,
					args: r.args,
				},
				freeze: 1
			});
		});
	},

	show_qty_prompt_for_multiple_work_orders: function(work_orders) {
		work_orders = frappe.utils.deep_clone(work_orders);
		for (let [i, d] of work_orders.entries()) {
			if (!erpnext.manufacturing.can_finish_work_order(d)) {
				frappe.throw(__("Work Order {0} cannot be finished", ["<b>" + d.name + "</b>"]));
			}

			d.idx = i + 1;
			[d.max, d.max_with_allowance] = erpnext.manufacturing.get_max_transferable_qty(d, "Manufacture");
			[d.work_order, d.finished_qty] = [d.name, d.max];
		}

		return new Promise((resolve, reject) => {
			let doc = {
				work_orders: work_orders
			};

			let fields = [{
				label: __("Work Orders"),
				fieldname: "work_orders",
				fieldtype: "Table",
				cannot_add_rows: true,
				in_place_edit: true,
				data: doc.work_orders,
				fields: [
					{
						label: __('Work Order'),
						fieldname: "work_order",
						fieldtype: "Link",
						options: "Work Order",
						read_only: 1,
						in_list_view: 1,
						reqd: 1,
						columns: 2,
					},
					{
						label: __('Production Item'),
						fieldname: "production_item",
						fieldtype: "Link",
						options: "Item",
						read_only: 1,
					},
					{
						label: __('Item Name'),
						fieldname: "item_name",
						fieldtype: "Data",
						read_only: 1,
						in_list_view: 1,
						columns: 4,
					},
					{
						label: __('Order Qty'),
						fieldname: "qty",
						fieldtype: "Float",
						read_only: 1,
						in_list_view: 1,
						columns: 2,
					},
					{
						label: __('Finished Qty'),
						fieldname: "finished_qty",
						fieldtype: "Float",
						in_list_view: 1,
						reqd: 1,
						columns: 2,
					},
				]
			}];

			for (let hook of erpnext.manufacturing.multiple_work_orders_qty_prompt_hooks || []) {
				hook(doc, fields);
			}

			let dialog = new frappe.ui.Dialog({
				title: __("Enter Finished Qty"),
				doc: doc,
				fields: fields,
				size: "extra-large",
				static: true,
				no_submit_on_enter: true,
				primary_action: function() {
					let data = dialog.get_values();

					doc.work_orders.forEach(d => {
						if (flt(d.finished_qty) > d.max_with_allowance) {
							frappe.msgprint(__('Finished Qty {0} can not be more than {1} for Work Order {2}',
								[format_number(d.finished_qty), format_number(d.max_with_allowance), d.work_order]));
							reject();
						}
					});

					let send_to_stock_entry_fieldnames = fields.filter(f => f.send_to_stock_entry).map(f => f.fieldname);
					let stock_entry_args = {};
					for (let fieldname of send_to_stock_entry_fieldnames) {
						if (data[fieldname]) {
							stock_entry_args[fieldname] = data[fieldname];
						}
					}

					resolve({
						work_orders: data.work_orders,
						args: stock_entry_args
					});
					dialog.hide();
				},
				primary_action_label: __('Submit'),
			});

			dialog.show();
		});
	},

	get_max_transferable_qty: (doc, purpose) => {
		let producible_qty_with_allowance = erpnext.manufacturing.get_qty_with_allowance(doc.producible_qty, doc);

		let pending_qty = 0;
		let pending_qty_with_allowance = 0;

		if (doc.skip_transfer) {
			pending_qty = flt(doc.producible_qty) - flt(doc.produced_qty);
			pending_qty_with_allowance = producible_qty_with_allowance - flt(doc.produced_qty);
		} else {
			if (purpose === 'Manufacture') {
				let qty_to_produce = Math.min(flt(doc.material_transferred_for_manufacturing), flt(doc.qty));
				pending_qty = qty_to_produce - flt(doc.produced_qty);
				pending_qty_with_allowance = flt(doc.material_transferred_for_manufacturing) - flt(doc.produced_qty);
			} else {
				pending_qty = flt(doc.producible_qty) - flt(doc.material_transferred_for_manufacturing);
				pending_qty_with_allowance = producible_qty_with_allowance - flt(doc.material_transferred_for_manufacturing);
			}
		}

		pending_qty = Math.max(pending_qty, 0);

		let qty_precision = erpnext.manufacturing.get_work_order_precision();
		return [flt(pending_qty, qty_precision), flt(pending_qty_with_allowance, qty_precision)];
	},

	get_qty_with_allowance: function (qty, doc) {
		let allowance_percentage = erpnext.manufacturing.get_over_production_allowance(doc);
		let qty_with_allowance = flt(qty) + flt(qty) * allowance_percentage / 100;
		return flt(qty_with_allowance, erpnext.manufacturing.get_work_order_precision())
	},

	get_over_production_allowance: function (doc) {
		if (doc.max_qty && doc.qty) {
			return flt(doc.max_qty) / flt(doc.qty) * 100 - 100
		} else {
			return flt(frappe.defaults.get_default('overproduction_percentage_for_work_order'))
		}
	},

	get_subcontractable_qty: function (doc) {
		let production_completed_qty = Math.max(flt(doc.produced_qty), flt(doc.material_transferred_for_manufacturing));
		let subcontractable_qty = flt(doc.producible_qty) - flt(doc.scrap_qty) - production_completed_qty;
		return flt(subcontractable_qty, erpnext.manufacturing.get_work_order_precision());
	},

	show_progress_for_production: function(doc, frm) {
		let qty_precision = erpnext.manufacturing.get_work_order_precision();

		let pending_production;
		if (doc.skip_transfer) {
			pending_production = flt(doc.producible_qty - doc.produced_qty, qty_precision);
		} else {
			pending_production = flt(doc.material_transferred_for_manufacturing - doc.produced_qty, qty_precision);
		}
		pending_production = Math.max(pending_production, 0);

		let pending_subcontract = flt(doc.subcontract_order_qty - doc.subcontract_received_qty, qty_precision);
		pending_subcontract = Math.max(pending_subcontract, 0);

		return erpnext.utils.show_progress_for_qty({
			frm: frm,
			as_html: !frm,
			title: __('Production Status'),
			total_qty: doc.qty,
			progress_bars: [
				{
					title: __("<b>Produced:</b> {0} / {1} {2} ({3}%)", [
						format_number(doc.produced_qty),
						format_number(doc.producible_qty),
						doc.stock_uom,
						format_number(doc.producible_qty ? doc.produced_qty / doc.producible_qty * 100: 0, null, 1),
					]),
					completed_qty: doc.produced_qty,
					progress_class: "progress-bar-success",
					add_min_width: doc.producible_qty ? 0.5 : 0,
				},
				{
					title: __("<b>Production Remaining:</b> {0} {1}", [format_number(pending_production), doc.stock_uom]),
					completed_qty: pending_production,
					progress_class: "progress-bar-warning",
				},
				{
					title: __("<b>Subcontract Received:</b> {0} / {1} {2} ({3}%)", [
						format_number(doc.subcontract_received_qty),
						format_number(doc.subcontract_order_qty),
						doc.stock_uom,
						format_number(doc.subcontract_received_qty / doc.subcontract_order_qty * 100, null, 1),
					]),
					completed_qty: doc.subcontract_received_qty,
					progress_class: "progress-bar-info",
					add_min_width: doc.subcontract_order_qty && !doc.producible_qty ? 0.5 : 0,
				},
				{
					title: __("<b>Subcontract Remaining:</b> {0} {1}", [format_number(pending_subcontract), doc.stock_uom]),
					completed_qty: pending_subcontract,
					progress_class: "progress-bar-yellow",
				},
			],
		});
	},

	show_progress_for_packing: function (doc, frm) {
		let qty_precision = erpnext.manufacturing.get_work_order_precision();
		let packed_qty = doc.packed_qty;
		let pending_complete = flt(flt(doc.completed_qty) - flt(doc.packed_qty), qty_precision);

		return erpnext.utils.show_progress_for_qty({
			frm: frm,
			as_html: !frm,
			title: __('Packing Status'),
			total_qty: doc.qty,
			progress_bars: [
				{
					title: __("<b>Packed:</b> {0} {1} ({2}%)", [
						format_number(packed_qty),
						doc.stock_uom,
						format_number(packed_qty / doc.qty * 100, null, 1),
					]),
					completed_qty: packed_qty,
					progress_class: "progress-bar-success",
					add_min_width: 0.5,
				},
				{
					title: __("<b>Remaining:</b> {0} {1}", [format_number(pending_complete), doc.stock_uom]),
					completed_qty: pending_complete,
					progress_class: "progress-bar-warning",
				},
			],
		});
	},

	get_work_order_precision: function () {
		let qty_df = frappe.meta.get_docfield("Work Order", "qty");
		return frappe.meta.get_field_precision(qty_df);
	},

	can_start_work_order: function (doc) {
		if (!erpnext.manufacturing.has_stock_entry_permission()) {
			return false;
		}
		if (doc.docstatus != 1 || ["Completed", "Stopped"].includes(doc.status)) {
			return false;
		}

		return (
			!doc.skip_transfer
			&& doc.transfer_material_against != 'Job Card'
			&& flt(doc.material_transferred_for_manufacturing) < flt(doc.producible_qty)
			&& flt(doc.produced_qty) < flt(doc.qty)
		);
	},

	can_finish_work_order: function (doc) {
		if (!erpnext.manufacturing.has_stock_entry_permission()) {
			return false;
		}
		if (doc.docstatus != 1 || ["Completed", "Stopped"].includes(doc.status)) {
			return false;
		}

		if (doc.skip_transfer) {
			return flt(doc.produced_qty) < flt(doc.producible_qty);
		} else {
			return flt(doc.produced_qty) < flt(doc.material_transferred_for_manufacturing);
		}
	},

	has_stock_entry_permission: function () {
		return frappe.model.can_write("Stock Entry");
	}
});
