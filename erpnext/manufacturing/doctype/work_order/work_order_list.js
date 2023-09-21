frappe.listview_settings['Work Order'] = {
	add_fields: [
		"status", "docstatus", "production_status", "per_produced",
		"skip_transfer", "transfer_material_against",
		"qty", "max_qty", "produced_qty", "material_transferred_for_manufacturing",
		"production_item", "item_name", "stock_uom",
		"packing_slip_required", "packed_qty", "packing_status", "per_packed",
		"order_line_no",
	],

	get_indicator: function(doc) {
		if (doc.status==="Submitted") {
			return [__("Not Started"), "orange", "status,=,Submitted"];
		} else {
			return [__(doc.status), {
				"Draft": "red",
				"Stopped": "red",
				"Not Started": "orange",
				"In Process": "yellow",
				"Completed": "green",
				"Cancelled": "light-gray"
			}[doc.status], "status,=," + doc.status];
		}
	},

	onload: function(listview) {
		listview.page.add_action_item(__("Finish Multiple"), function() {
			let work_orders = listview.get_checked_items();
			erpnext.manufacturing.finish_multiple_work_orders(work_orders);
		});
	},

	button: {
		show(doc) {
			return erpnext.manufacturing.can_start_work_order(doc) || erpnext.manufacturing.can_finish_work_order(doc);
		},
		get_label(doc) {
			if (erpnext.manufacturing.can_finish_work_order(doc)) {
				return __('Finish');
			} else if (erpnext.manufacturing.can_start_work_order(doc)) {
				return __('Start');
			}
		},
		get_class(doc) {
			if (erpnext.manufacturing.can_finish_work_order(doc)) {
				return "btn-primary";
			} else {
				return "btn-default";
			}
		},
		get_description(doc) {
			return this.get_label(doc);
		},
		action(doc) {
			let method;
			if (erpnext.manufacturing.can_finish_work_order(doc)) {
				method = () => erpnext.manufacturing.make_stock_entry(doc, "Manufacture");
			} else if (erpnext.manufacturing.can_start_work_order(doc)) {
				method = () => erpnext.manufacturing.make_stock_entry(doc, 'Material Transfer for Manufacture');
			}

			if (method) {
				method().then(() => {
					if (cur_list && cur_list.doctype == "Work Order") {
						cur_list.refresh();
					}
				});
			}
		}
	},
};
