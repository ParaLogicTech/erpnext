frappe.provide("erpnext.manufacturing");

erpnext.manufacturing.stock_entry_qty_prompt_hooks = [];
erpnext.manufacturing.job_card_qty_prompt_hooks = [];
erpnext.manufacturing.multiple_work_orders_qty_prompt_hooks = [];

$.extend(erpnext.manufacturing, {
	start_work_order: function (doc) {
		if (doc.docstatus != 1) {
			return;
		}

		return erpnext.manufacturing.make_stock_entry_from_work_order(doc, "Material Transfer for Manufacture");
	},

	finish_work_order: function(doc, reload_doc) {
		if (doc.docstatus != 1) {
			return;
		}

		if (reload_doc) {
			frappe.model.clear_doc("Work Order", doc.name);
		}

		// get full doc instead of relying on argument which may have incomplete doc (like from list view without operations table)
		return frappe.model.with_doc("Work Order", doc.name).then(r => {
			let producible_qty = flt(r.skip_transfer ? r.producible_qty : r.material_transferred_for_manufacturing);

			let has_pending_operation = (r.operations || []).filter(d => d.completed_qty < producible_qty).length;
			let min_operation_completed_qty = Math.min(...r.operations.map(d => flt(d.completed_qty)));
			let can_backflush = flt(r.produced_qty) < min_operation_completed_qty;

			if (has_pending_operation && can_backflush) {
				return erpnext.manufacturing.show_finish_operation_or_work_order_dialog(r);
			} else if (has_pending_operation) {
				return erpnext.manufacturing.make_job_card_from_work_order(r);
			} else {
				return erpnext.manufacturing.make_stock_entry_from_work_order(r, "Manufacture");
			}
		});
	},

	show_finish_operation_or_work_order_dialog: function(doc) {
		return new Promise((resolve) => {
			let html = `
				<div class="d-flex justify-content-center">
					<button type="button" class="btn btn-primary btn-finish-operation">
						${__("Finish Operation")}
					</button>
					<button type="button" class="btn btn-primary btn-finish-work-order ml-4">
						${__("Finish Work Order")}
					</button>
				</div>
			`;

			let dialog = new frappe.ui.Dialog({
				title: __("Select Action"),
				fields: [
					{fieldtype: "HTML", options: html}
				],
			});

			dialog.show();

			$('.btn-finish-operation', dialog.$wrapper).click(function () {
				dialog.hide();
				resolve(erpnext.manufacturing.make_job_card_from_work_order(doc));
			});
			$('.btn-finish-work-order', dialog.$wrapper).click(function () {
				dialog.hide();
				resolve(erpnext.manufacturing.make_stock_entry_from_work_order(doc, "Manufacture"));
			});
		});
	},

	make_job_card_from_work_order: function(doc) {
		return erpnext.manufacturing.show_qty_prompt_for_job_card(doc).then(args => {
			return frappe.call({
				method: "erpnext.manufacturing.doctype.work_order.work_order.make_job_card",
				args: {
					"work_order": doc.name,
					"operation": args.operation,
					"workstation": args.workstation,
					"qty": args.qty,
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

	show_qty_prompt_for_job_card: function(doc) {
		return new Promise((resolve, reject) => {
			let max = 0
			let max_with_allowance = 0;
			let row = null;

			frappe.model.with_doctype("Work Order", () => {
				let operation_options = doc.operations.map(d => d.operation);
				let fields = [
					{
						label: __('Select Operation'),
						fieldname: 'operation',
						fieldtype: 'Select',
						options: operation_options,
						reqd: 1,
						onchange: () => {
							let operation = dialog.get_value('operation');
							let workstation = null;
							let qty = 0
							let completed_qty = 0;
							let description = "";

							if (operation) {
								row = doc.operations.find(d => d.operation == operation);
								[max, max_with_allowance] = erpnext.manufacturing.get_max_qty_for_operation(doc, row);

								workstation = row.workstation;
								completed_qty = flt(row.completed_qty);
								qty = max;

								description = __("Max: {0}", [frappe.format(max, {"fieldtype": "Float"}, {"inline": 1})]);
							}

							dialog.set_value("workstation", workstation);
							dialog.set_value("qty", qty);
							dialog.set_value("completed_qty", completed_qty);
							dialog.set_df_property("qty", "description", description);
						},
					},
					{
						label: __('Workstation'),
						fieldname: 'workstation',
						fieldtype: 'Link',
						options: 'Workstation',
						reqd: 1,
						get_query: () => {
							let operation = dialog.get_value('operation');
							return erpnext.queries.workstation(operation);
						}
					},
					{
						label: __('Qty'),
						fieldname: 'qty',
						fieldtype: 'Float',
						reqd: 1,
						default: 0,
					},
					{
						fieldtype: 'Section Break',
					},
					{
						label: __('Qty to Produce'),
						fieldname: 'qty_to_produce',
						fieldtype: 'Float',
						default: flt(doc.producible_qty),
						read_only: 1,
					},
					{
						fieldtype: 'Column Break',
					},
					{
						label: __('Completed Qty'),
						fieldname: 'completed_qty',
						fieldtype: 'Float',
						default: 0,
						read_only: 1,
					},
				]

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

				for (let hook of erpnext.manufacturing.job_card_qty_prompt_hooks || []) {
					hook(doc, fields);
				}

				let dialog = new frappe.ui.Dialog({
					title: __('Finish Operation'),
					fields: fields,
					static: true,
					primary_action: function() {
						let data = dialog.get_values();
						if (flt(data.qty) > max_with_allowance) {
							frappe.msgprint(__('Quantity can not be more than {0}', [
								frappe.format(max_with_allowance, {"fieldtype": "Float"}, {"inline": 1}),
							]));
							reject();
						}

						dialog.hide();
						resolve({
							operation: row.operation,
							workstation: data.workstation,
							qty: data.qty,
						});
					},
					primary_action_label: __('Finish')
				});
				dialog.show();
			});
		});
	},

	make_stock_entry_from_work_order: function(doc, purpose) {
		return erpnext.manufacturing.show_qty_prompt_for_stock_entry(doc, purpose).then(r => {
			return frappe.call({
				method: "erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry",
				args: {
					"work_order_id": doc.name,
					"purpose": purpose,
					"qty": r.data.qty,
					"process_loss_qty": r.data.process_loss_qty,
					"use_alternative_item": r.data.use_alternative_item,
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

	show_qty_prompt_for_stock_entry: function(doc, purpose) {
		return new Promise((resolve) => {
			return frappe.model.with_doctype("Work Order", () => {
				let [max, max_with_allowance] = erpnext.manufacturing.get_max_transferable_qty(doc, purpose);

				const calculate_process_loss_qty = () => {
					let [max_qty, max_qty_with_allowance] = erpnext.manufacturing.get_max_transferable_qty(doc, purpose, true);

					let values = dialog.get_values();
					if (!values.process_loss_remaining || !doc.allow_process_loss) {
						return;
					}

					let production_qty = flt(values.qty);
					if (production_qty >= max_qty) {
						return dialog.set_value("process_loss_qty", 0);
					} else if (production_qty > 0) {
						return dialog.set_value("process_loss_qty", max_qty - production_qty);
					}
				};

				let fields = [
					{
						fieldtype: 'Float',
						label: __('Qty for {0}', [purpose]),
						fieldname: 'qty',
						description: __('Max: {0}', [frappe.format(max, {"fieldtype": "Float"}, {"inline": 1})]),
						reqd: 1,
						default: max,
						onchange: () => calculate_process_loss_qty(),
					},
				];

				if (purpose === "Manufacture" && doc.allow_process_loss) {
					fields.push({
						fieldtype: 'Check',
						label: __('Consider Remaining as Process Loss'),
						fieldname: 'process_loss_remaining',
						default: cint(frappe.defaults.get_default('process_loss_remaining_by_default')),
						onchange: () => calculate_process_loss_qty(),
					})
					fields.push({
						fieldtype: 'Float',
						label: __('Process Loss Qty'),
						fieldname: 'process_loss_qty',
						default: 0,
					});
				}

				fields = fields.concat([
					{
						fieldtype: 'Check',
						label: __('Use Alternative Item for Out of Stock Materials'),
						fieldname: 'use_alternative_item',
					},
					{
						fieldtype: 'Section Break',
					},
					{
						label: __('Qty to Produce'),
						fieldname: 'qty_to_produce',
						fieldtype: 'Float',
						default: flt(doc.producible_qty),
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

				for (let hook of erpnext.manufacturing.stock_entry_qty_prompt_hooks || []) {
					hook(doc, fields, purpose);
				}

				let dialog = new frappe.ui.Dialog({
					title: __(purpose),
					fields: fields,
					static: true,
					primary_action: function() {
						let data = dialog.get_values();
						if (flt(data.qty) > max_with_allowance) {
							frappe.msgprint(__('Quantity can not be more than {0}', [
								frappe.format(max_with_allowance, {"fieldtype": "Float"}, {"inline": 1})
							]));
							return;
						}

						let send_to_stock_entry_fieldnames = fields.filter(f => f.send_to_stock_entry).map(f => f.fieldname);
						let stock_entry_args = {};
						for (let fieldname of send_to_stock_entry_fieldnames) {
							if (data[fieldname]) {
								stock_entry_args[fieldname] = data[fieldname];
							}
						}

						data.purpose = purpose;

						dialog.hide();
						resolve({
							data: data,
							args: stock_entry_args,
						});
					},
					primary_action_label: __('Submit')
				});
				dialog.show();
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
							frappe.msgprint(__('Finished Qty {0} can not be more than {1} for Work Order {2}', [
								frappe.format(d.finished_qty, {"fieldtype": "Float"}, {"inline": 1}),
								frappe.format(d.max_with_allowance, {"fieldtype": "Float"}, {"inline": 1}),
								d.work_order
							]));
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

	get_max_transferable_qty: (doc, purpose, get_max_operation_qty) => {
		let producible_qty_with_allowance = erpnext.manufacturing.get_qty_with_allowance(doc.producible_qty, doc);

		let pending_qty = 0;
		let pending_qty_with_allowance = 0;

		if (doc.skip_transfer) {
			pending_qty = flt(doc.producible_qty) - flt(doc.produced_qty);
			pending_qty_with_allowance = producible_qty_with_allowance - flt(doc.produced_qty);
		} else {
			if (purpose == "Material Transfer for Manufacture") {
				pending_qty = flt(doc.producible_qty) - flt(doc.material_transferred_for_manufacturing);
				pending_qty_with_allowance = producible_qty_with_allowance - flt(doc.material_transferred_for_manufacturing);
			} else {
				pending_qty = flt(doc.material_transferred_for_manufacturing) - flt(doc.produced_qty) - flt(doc.process_loss_qty);
				pending_qty_with_allowance = pending_qty;
			}
		}

		// Operation completion adjustment
		if (["Manufacture", "Material Consumption for Manufacture"].includes(purpose) && doc.operations?.length) {
			let operation_completed_qty;
			if (get_max_operation_qty) {
				operation_completed_qty = Math.max(...doc.operations.map(d => flt(d.completed_qty)));
			} else {
				operation_completed_qty = Math.min(...doc.operations.map(d => flt(d.completed_qty)));
			}

			pending_qty = Math.min(pending_qty, operation_completed_qty - flt(doc.produced_qty));
		}

		pending_qty = Math.max(pending_qty, 0);

		let qty_precision = erpnext.manufacturing.get_work_order_precision();
		return [flt(pending_qty, qty_precision), flt(pending_qty_with_allowance, qty_precision)];
	},

	get_max_qty_for_operation: (doc, operation_row) => {
		let producible_qty_with_allowance = erpnext.manufacturing.get_qty_with_allowance(doc.producible_qty, doc);

		let pending_qty = 0;
		let pending_qty_with_allowance = 0;

		if (doc.skip_transfer) {
			pending_qty = flt(doc.producible_qty) - flt(operation_row.completed_qty);
			pending_qty_with_allowance = producible_qty_with_allowance - flt(operation_row.completed_qty);
		} else {
			pending_qty = flt(doc.material_transferred_for_manufacturing) - flt(operation_row.completed_qty);
			pending_qty_with_allowance = pending_qty;
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
		let subcontractable_qty = flt(doc.producible_qty) - production_completed_qty;
		return flt(subcontractable_qty, erpnext.manufacturing.get_work_order_precision());
	},

	make_work_orders_from_order_dialog: function(items_data, doc, create_sub_assembly_work_orders) {
		let dialog_doc = {
			items: items_data,
		};

		const fields = [{
			label: "Items to Produce",
			fieldtype: "Table",
			fieldname: "items",
			cannot_add_rows: 1,
			description: __("Confirm BOM and Production Qty"),
			fields: [
				{
					fieldname: "item_code",
					label: __("Production Item"),
					fieldtype: "Link",
					options: "Item",
					in_list_view: 1,
					read_only: 1,
					reqd: 1,
					columns: 5,
				},
				{
					fieldname: "bom_no",
					label: __("BOM No"),
					fieldtype: "Link",
					options: "BOM",
					reqd: 1,
					in_list_view: 1,
					columns: 3,
					get_query: function (doc) {
						return {
							filters: {
								item: doc.item_code,
								is_active: 1,
								docstatus: 1,
							}
						};
					}
				},
				{
					fieldname: "production_qty",
					label: __("Qty"),
					fieldtype: "Float",
					reqd: 1,
					in_list_view: 1,
					columns: 1,
				},
				{
					fieldname: "stock_uom",
					label: __("UOM"),
					fieldtype: "Data",
					in_list_view: 1,
					read_only: 1,
					columns: 1,
				},
				{
					fieldtype: "Data",
					fieldname: "sales_order_item",
					reqd: 1,
					label: __("Sales Order Item"),
					hidden: 1
				},
				{
					fieldtype: "Data",
					fieldname: "work_order_item",
					reqd: 1,
					label: __("Work Order Item"),
					hidden: 1
				},
			],
			data: dialog_doc.items,
		}];

		let dialog = new frappe.ui.Dialog({
			title: __("Select Items to Produce"),
			fields: fields,
			doc: dialog_doc,
			size: "extra-large",
			primary_action: () => {
				let values = dialog.get_values();
				for (let d of values.items) {
					if (doc.doctype == "Sales Order") {
						d.sales_order = doc.name;
					} else if (doc.doctype == "Work Order") {
						d.parent_work_order = doc.name;
					}

					d.customer = doc.customer;
					d.customer_name = doc.customer_name;
					d.project = doc.project;
				}

				return frappe.call({
					method: "erpnext.manufacturing.doctype.work_order.work_order.create_work_orders",
					args: {
						items: values.items,
						company: doc.company,
						create_sub_assembly_work_orders: cint(create_sub_assembly_work_orders),
					},
					freeze: true,
					callback: (r) => {
						if (r.message) {
							frappe.msgprint({
								message: __("Work Orders Created: {0}", [
									r.message.map((d) => `<a href="${frappe.utils.get_form_link("Work Order", d)}">${d}</a>`).join(', ')
								]),
								indicator: "green",
							})
						}
						dialog.hide();
					}
				});
			},
			primary_action_label: __("Create")
		});
		dialog.show();
	},

	show_progress_for_production: function(doc, frm, opts) {
		opts = opts || {};

		let qty_precision = erpnext.manufacturing.get_work_order_precision();

		let pending_production;
		if (doc.skip_transfer) {
			pending_production = flt(doc.producible_qty - doc.produced_qty - doc.process_loss_qty, qty_precision);
		} else {
			pending_production = flt(doc.material_transferred_for_manufacturing - doc.produced_qty - doc.process_loss_qty, qty_precision);
		}
		pending_production = Math.max(pending_production, 0);

		let pending_subcontract = flt(doc.subcontract_order_qty - doc.subcontract_received_qty, qty_precision);
		pending_subcontract = Math.max(pending_subcontract, 0);

		let rejected_qty = opts.show_rejection_reconciliation ? flt(doc.rejected_qty) : 0;
		let reconciled_qty = opts.show_rejection_reconciliation ? flt(doc.reconciled_qty) : 0;

		let process_loss_label = opts.process_loss_label || __("Process Loss");

		return erpnext.utils.show_progress_for_qty({
			frm: frm,
			as_html: !frm,
			title: __('Production Status'),
			total_qty: doc.qty,
			progress_bars: [
				{
					title: __("<b>Produced:</b> {0} / {1} {2} ({3}%)", [
						frappe.format(doc.produced_qty, {'fieldtype': 'Float'}, { inline: 1 }),
						frappe.format(doc.producible_qty, {'fieldtype': 'Float'}, { inline: 1 }),
						doc.stock_uom,
						format_number(doc.producible_qty ? doc.produced_qty / doc.producible_qty * 100: 0, null, 1),
					]),
					completed_qty: doc.produced_qty,
					progress_class: "progress-bar-success",
					add_min_width: doc.producible_qty ? 0.5 : 0,
				},
				{
					title: `<b>${process_loss_label}:</b> ` + __("{0} {1} ({2}%)", [
						frappe.format(doc.process_loss_qty, {'fieldtype': 'Float'}, { inline: 1 }),
						doc.stock_uom,
						format_number(doc.producible_qty ? doc.process_loss_qty / doc.producible_qty * 100: 0, null, 1),
					]),
					completed_qty: doc.process_loss_qty,
					progress_class: "progress-bar-info",
				},
				{
					title: __("<b>Rejected:</b> {0} {1} ({2}%)", [
						frappe.format(rejected_qty, {'fieldtype': 'Float'}, { inline: 1 }),
						"Meter",
						format_number(rejected_qty / doc.qty * 100, null, 1),
					]),
					completed_qty: rejected_qty,
					description_only: true,
				},
				{
					title: __("<b>Reconciled:</b> {0} {1} ({2}%)", [
						frappe.format(reconciled_qty, {'fieldtype': 'Float'}, { inline: 1 }),
						"Meter",
						format_number(reconciled_qty / doc.qty * 100, null, 1),
					]),
					completed_qty: reconciled_qty,
					description_only: true,
				},
				{
					title: __("<b>Production Remaining:</b> {0} {1}", [frappe.format(pending_production, {'fieldtype': 'Float'}, { inline: 1 }), doc.stock_uom]),
					completed_qty: pending_production,
					progress_class: "progress-bar-warning",
				},
				{
					title: __("<b>Subcontract Received:</b> {0} / {1} {2} ({3}%)", [
						frappe.format(doc.subcontract_received_qty, {'fieldtype': 'Float'}, { inline: 1 }),
						frappe.format(doc.subcontract_order_qty, {'fieldtype': 'Float'}, { inline: 1 }),
						doc.stock_uom,
						format_number(doc.subcontract_received_qty / doc.subcontract_order_qty * 100, null, 1),
					]),
					completed_qty: doc.subcontract_received_qty,
					progress_class: "progress-bar-info",
					add_min_width: doc.subcontract_order_qty && !doc.producible_qty ? 0.5 : 0,
				},
				{
					title: __("<b>Subcontract Remaining:</b> {0} {1}", [frappe.format(pending_subcontract, {'fieldtype': 'Float'}, { inline: 1 }), doc.stock_uom]),
					completed_qty: pending_subcontract,
					progress_class: "progress-bar-yellow",
				},
			],
		});
	},

	show_progress_for_packing: function (doc, frm) {
		let qty_precision = erpnext.manufacturing.get_work_order_precision();
		let total_qty = flt(doc.qty);
		let packed_qty = flt(doc.packed_qty);
		let rejected_qty = flt(doc.rejected_qty);
		let reconciled_qty = flt(doc.reconciled_qty);
		let pending_complete = flt(
			flt(doc.completed_qty) - flt(doc.packed_qty) - flt(doc.rejected_qty) - flt(doc.reconciled_qty),
			qty_precision
		);
		pending_complete = Math.max(pending_complete, 0);

		return erpnext.utils.show_progress_for_qty({
			frm: frm,
			as_html: !frm,
			title: __('Packing Status'),
			total_qty: total_qty,
			progress_bars: [
				{
					title: __("<b>Packed:</b> {0} {1} ({2}%)", [
						frappe.format(packed_qty, {'fieldtype': 'Float'}, { inline: 1 }),
						doc.stock_uom,
						format_number(packed_qty / total_qty * 100, null, 1),
					]),
					completed_qty: packed_qty,
					progress_class: "progress-bar-success",
					add_min_width: 0.5,
				},
				{
					title: __("<b>Rejected:</b> {0} {1} ({2}%)", [
						frappe.format(rejected_qty, {'fieldtype': 'Float'}, { inline: 1 }),
						"Meter",
						format_number(rejected_qty / total_qty * 100, null, 1),
					]),
					completed_qty: rejected_qty,
					progress_class: "progress-bar-yellow",
				},
				{
					title: __("<b>Reconciled:</b> {0} {1} ({2}%)", [
						frappe.format(reconciled_qty, {'fieldtype': 'Float'}, { inline: 1 }),
						"Meter",
						format_number(reconciled_qty / total_qty * 100, null, 1),
					]),
					completed_qty: reconciled_qty,
					progress_class: "progress-bar-info",
				},
				{
					title: __("<b>Remaining:</b> {0} {1}", [frappe.format(pending_complete, {'fieldtype': 'Float'}, { inline: 1 }), doc.stock_uom]),
					completed_qty: pending_complete,
					progress_class: "progress-bar-warning",
				},
			],
		});
	},

	show_progress_for_operation: function (doc, row, frm) {
		let qty_precision = erpnext.manufacturing.get_work_order_precision();

		let pending_operation;
		if (doc.skip_transfer) {
			pending_operation = flt(doc.producible_qty - flt(row.completed_qty), qty_precision);
		} else {
			pending_operation = flt(doc.material_transferred_for_manufacturing - flt(row.completed_qty), qty_precision);
		}

		return erpnext.utils.show_progress_for_qty({
			frm: frm,
			as_html: !frm,
			title: __('{0} Operation Status', [row.operation]),
			total_qty: doc.producible_qty,
			progress_bars: [
				{
					title: __("<b>Completed:</b> {0} / {1} {2} ({3}%)", [
						frappe.format(row.completed_qty, {'fieldtype': 'Float'}, { inline: 1 }),
						frappe.format(doc.producible_qty, {'fieldtype': 'Float'}, { inline: 1 }),
						doc.stock_uom,
						format_number(doc.producible_qty ? flt(row.completed_qty) / doc.producible_qty * 100 : 0, null, 1),
					]),
					completed_qty: row.completed_qty,
					progress_class: "progress-bar-success",
					add_min_width: doc.producible_qty ? 0.5 : 0,
				},
				{
					title: __("<b>Remaining:</b> {0} {1}", [frappe.format(pending_operation, {'fieldtype': 'Float'}, { inline: 1 }), doc.stock_uom]),
					completed_qty: pending_operation,
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
			return flt(doc.produced_qty) + flt(doc.process_loss_qty) < flt(doc.material_transferred_for_manufacturing);
		}
	},

	has_stock_entry_permission: function () {
		return frappe.model.can_write("Stock Entry");
	},
});
