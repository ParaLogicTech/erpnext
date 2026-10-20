// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext.bom");

erpnext.bom.BomController = class BomController extends erpnext.TransactionController {
	setup() {
		this.frm.custom_make_buttons = {
			"Work Order": "Work Order",
			"Quality Inspection": "Quality Inspection",
		};

		this.setup_queries();
	}

	refresh() {
		erpnext.hide_company(this.frm);
		this.set_dynamic_labels();

		this.frm.set_indicator_formatter("item_code", (doc) => {
			if (doc.for_packing_slip) {
				return "light-blue";
			}
			if (doc.original_item) {
				return (doc.item_code != doc.original_item) ? "orange" : "";
			}
		});

		this.setup_buttons();
	}

	onload_post_render() {
		this.frm.get_field("items").grid.set_multiple_add("item_code", "qty");
	}

	validate() {
		this.calculate_cost();
	}

	setup_queries() {
		this.setup_warehouse_query();

		this.frm.set_query("item", () => erpnext.queries.item({
			name: ["!=", this.frm.doc.item]
		}));

		this.frm.set_query("uom", "items", (doc, cdt, cdn) => {
			let item = frappe.get_doc(cdt, cdn);
			return erpnext.queries.item_uom(item.item_code);
		});

		this.frm.set_query("bom_no", "items", (doc, cdt, cdn) => {
			let row = frappe.get_doc(cdt, cdn);
			return {
				filters: {
					item: row.item_code,
					is_active: 1,
					docstatus: 1,
					company: this.frm.doc.company,
				}
			};
		});

		this.frm.set_query("project", () => {
			return{
				filters: {
					status: ['not in', ['Completed', 'Cancelled']]
				}
			};
		});

		this.frm.set_query("workstation", "operations", (doc, cdt, cdn) => {
			let row = frappe.get_doc(cdt, cdn);
			return erpnext.queries.workstation(row.operation);
		});

		this.frm.set_query("carton_type", () => {
			return erpnext.queries.carton_type(this.frm.doc.item);
		});
	}

	setup_buttons() {
		if (!this.frm.doc.__islocal && this.frm.doc.docstatus < 2) {
			this.frm.add_custom_button(__("Update Cost"), () => {
				this.update_cost();
			});
			this.frm.add_custom_button(__("Browse BOM"), () => {
				frappe.route_options = {
					"bom": this.frm.doc.name
				};
				frappe.set_route("Tree", "BOM");
			});
		}

		if (this.frm.doc.docstatus == 1) {
			this.frm.add_custom_button(__("Work Order"), () => {
				this.make_work_order();
			}, __("Create"));

			if (this.frm.doc.inspection_required) {
				this.frm.add_custom_button(__("Quality Inspection"), () => {
					this.make_quality_inspection();
				}, __("Create"));
			}

			this.frm.page.set_inner_btn_group_as_primary(__('Create'));
		}

		const has_alternative_items = (this.frm.doc.items || []).some(d => d.has_alternative_item);
		if (has_alternative_items && this.frm.doc.docstatus == 0) {
			this.frm.add_custom_button(__("Alternate Item"), () => {
				erpnext.utils.select_alternate_items({
					frm: this.frm,
					child_docname: "items",
					warehouse_field: "source_warehouse",
					child_doctype: "BOM Item",
					original_item_field: "original_item",
					condition: (d) => d.has_alternative_item,
				});
			});
		}
	}

	item() {
		if (this.frm.doc.item) {
			return frappe.call({
				method: "erpnext.manufacturing.doctype.work_order.work_order.get_item_details",
				args: {
					args: {
						item_code: this.frm.doc.item,
						company: this.frm.doc.company,
						project: this.frm.doc.project,
					},
					with_settings: 1,
					without_bom: 1,
				},
				callback: (r) => {
					if (r.message) {
						this.frm.set_value("packing_slip_required", cint(r.message.packing_slip_required));
						if (r.message.carton_type) {
							this.frm.set_value("carton_type", r.message.carton_type);
						}
					}
				}
			});
		}
	}

	carton_type() {
		return this.get_item_packaging_details();
	}

	item_code(doc, cdt, cdn) {
		let scrap_items = false;
		let row = frappe.get_doc(cdt, cdn);
		if (row.doctype == 'BOM Scrap Item') {
			scrap_items = true;
		}

		if (row.bom_no) {
			row.bom_no = "";
		}

		this.get_bom_material_detail(cdt, cdn, scrap_items, true);
	}

	quantity() {
		this.calculate_cost();
	}

	qty() {
		this.calculate_cost();
	}

	conversion_factor(doc, cdt, cdn) {
		if (frappe.meta.get_docfield(cdt, "stock_qty", cdn)) {
			let item = frappe.get_doc(cdt, cdn);
			frappe.model.round_floats_in(item, ["qty", "conversion_factor"]);
			item.stock_qty = flt(item.qty * item.conversion_factor);
			refresh_field("stock_qty", item.name, item.parentfield);
			this.update_cost();
		}
	}

	rate(doc, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		let scrap_items = false;
		if (cdt == 'BOM Scrap Item') {
			scrap_items = true;
		}

		if (row.bom_no && cdt != "BOM Scrap Item") {
			frappe.msgprint(__("You can not change rate if BOM mentioned against any item"));
			this.get_bom_material_detail(cdt, cdn, scrap_items);
		} else {
			this.calculate_cost();
		}
	}

	conversion_rate() {
		if(this.frm.doc.currency === this.get_company_currency()) {
			this.frm.set_value("conversion_rate", 1.0);
		} else {
			this.calculate_cost();
		}
	}

	buying_price_list() {
		this.apply_price_list();
	}

	plc_conversion_rate() {
		if (!this.in_apply_price_list) {
			this.apply_price_list(null, true);
		}
	}

	bom_no(doc, cdt, cdn) {
		this.get_bom_material_detail(cdt, cdn, false);
	}

	do_not_explode(doc, cdt, cdn) {
		this.get_bom_material_detail(cdt, cdn, false);
	}

	hour_rate() {
		this.calculate_cost();
	}

	time_in_mins() {
		this.hour_rate();
	}

	is_default() {
		if (this.frm.doc.is_default) {
			this.frm.set_value("is_active", 1)
		}
	}

	rm_cost_as_per() {
		if (["Valuation Rate", "Last Purchase Rate"].includes(this.frm.doc.rm_cost_as_per)) {
			this.frm.set_value("plc_conversion_rate", 1.0);
		}
	}

	routing() {
		if (this.frm.doc.routing) {
			return frappe.call({
				doc: this.frm.doc,
				method: "get_routing",
				freeze: true,
				callback: (r) => {
					if (!r.exc) {
						this.calculate_cost();
					}
				}
			});
		}
	}

	with_operations() {
		if (!cint(this.frm.doc.with_operations)) {
			this.frm.set_value("operations", []);
		}
	}

	operation(doc, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		if(!row.operation) {
			return;
		}

		frappe.call({
			method: "frappe.client.get",
			args: {
				doctype: "Operation",
				name: row.operation,
			},
			callback: (r) => {
				if(r.message.description) {
					frappe.model.set_value(row.doctype, row.name, "description", r.message.description);
				}
				if(r.message.workstation) {
					frappe.model.set_value(row.doctype, row.name, "workstation", r.message.workstation);
				}
			}
		});
	}

	workstation(doc, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		if(!row.workstation) {
			return;
		}

		frappe.call({
			method: "frappe.client.get",
			args: {
				doctype: "Workstation",
				name: row.workstation,
			},
			callback: (r) => {
				frappe.model.set_value(row.doctype, row.name, "base_hour_rate", r.message.hour_rate);
				frappe.model.set_value(row.doctype, row.name, "hour_rate",
					flt(flt(r.message.hour_rate) / flt(frm.doc.conversion_rate)), 2);

				this.calculate_cost();
			}
		});
	}

	items_remove() {
		this.calculate_cost();
	}

	operations_remove() {
		this.calculate_cost();
	}

	get_bom_material_detail(cdt, cdn, scrap_items, item_changed) {
		let row = frappe.get_doc(cdt, cdn);
		if (row.item_code) {
			return frappe.call({
				doc: this.frm.doc,
				method: "get_bom_material_detail",
				args: {
					item_code: row.item_code,
					bom_no: row.bom_no != null ? row.bom_no: '',
					scrap_items: scrap_items,
					qty: row.qty,
					stock_qty: row.stock_qty,
					skip_transfer_for_manufacture: item_changed ? null : row.skip_transfer_for_manufacture,
					uom: item_changed ? null : row.uom,
					stock_uom: item_changed ? null : row.stock_uom,
					conversion_factor: item_changed ? null : row.conversion_factor,
					do_not_explode: row.do_not_explode,
				},
				callback: (r) => {
					row = frappe.get_doc(cdt, cdn);
					$.extend(row, r.message);
					this.calculate_cost();
				},
				freeze: true
			});
		}
	}

	get_item_packaging_details() {
		return frappe.call({
			method: "erpnext.stock.get_item_details.get_item_packaging_details",
			args: {
				item_code: this.frm.doc.item,
				carton_type: this.frm.doc.carton_type,
				get_default: 0,
			},
			callback: (r) => {
				if (r.message) {
					return frappe.run_serially([
						() => this.frm.set_value(r.message),
						() => this.calculate_cost(),
					]);
				}
			}
		});
	}

	update_carton_type_items() {
		if (this.frm.doc.carton_type) {
			return this.update_package_type_items(this.frm.doc.carton_type);
		}
	}

	update_package_type_items(package_type) {
		if (!package_type) {
			return;
		}

		return frappe.call({
			method: "update_package_type_items",
			doc: this.frm.doc,
			freeze: true,
			args: {
				package_type: package_type,
			},
			callback: () => {
				this.frm.dirty();
				this.calculate_cost();
			}
		});
	}

	update_cost() {
		return frappe.call({
			method: "update_cost",
			doc: this.frm.doc,
			freeze: true,
			args: {
				update_parent: true,
				from_child_bom: false,
				save: this.frm.doc.docstatus === 1 ? 1 : 0,
			},
			callback: () => {
				if (this.frm.doc.docstatus == 0) {
					this.frm.dirty();
					this.calculate_cost();
				} else if (this.frm.doc.docstatus == 1) {
					this.frm.reload();
				}
			}
		});
	}

	calculate_taxes_and_totals() {
		this.calculate_cost();
	}

	calculate_cost() {
		let doc = this.frm.doc;

		doc.carton_qty = doc.qty_per_carton ? flt(doc.quantity) / flt(doc.qty_per_carton) : 0;

		this.calculate_operating_cost();
		this.calculate_raw_material_cost();
		this.calculate_scrap_material_cost();

		doc.total_cost = doc.total_operating_cost + doc.total_material_cost - doc.scrap_material_cost;
		doc.base_total_cost = doc.base_total_operating_cost + doc.base_total_material_cost - doc.base_scrap_material_cost;

		doc.unit_cost = doc.quantity ? doc.total_cost / flt(doc.quantity) : 0;
		doc.base_unit_cost = doc.quantity ? doc.base_total_cost / flt(doc.quantity) : 0;

		this.frm.refresh_fields();
	}

	calculate_operating_cost() {
		let doc = this.frm.doc;

		doc.operating_cost = 0.0;
		doc.base_operating_cost = 0.0;
		for (let d of doc.operations || []) {
			d.base_hour_rate = flt(d.hour_rate) * flt(doc.conversion_rate);
			d.operating_cost = flt(d.hour_rate) * flt(d.time_in_mins) / 60.0;
			d.base_operating_cost = d.operating_cost * flt(doc.conversion_rate);

			doc.operating_cost += d.operating_cost;
			doc.base_operating_cost += d.base_operating_cost;
		}

		doc.additional_operating_cost = 0.0;
		doc.base_additional_operating_cost = 0.0;
		for (let d of doc.additional_costs || []) {
			d.base_rate = flt(d.rate) * flt(doc.conversion_rate);
			d.amount = flt(d.rate) * flt(d.qty);
			d.base_amount = d.amount * flt(doc.conversion_rate);

			doc.additional_operating_cost += d.amount;
			doc.base_additional_operating_cost += d.base_amount;
		}

		doc.child_operating_cost = 0.0;
		doc.base_child_operating_cost = 0.0;
		for (let d of doc.items || []) {
			d.stock_qty = flt(d.qty) * flt(d.conversion_factor);
			d.child_operating_cost = flt(d.child_unit_operating_cost) * flt(d.stock_qty);
			d.base_child_operating_cost = d.child_operating_cost * flt(doc.conversion_rate);

			doc.child_operating_cost += d.child_operating_cost
			doc.base_child_operating_cost += d.base_child_operating_cost
		}

		doc.total_operating_cost = doc.operating_cost + doc.additional_operating_cost + doc.child_operating_cost;
		doc.base_total_operating_cost = doc.base_operating_cost + doc.base_additional_operating_cost + doc.base_child_operating_cost;

		doc.unit_operating_cost = doc.quantity ? doc.total_operating_cost / flt(doc.quantity) : 0;
		doc.base_unit_operating_cost = doc.quantity ? doc.base_total_operating_cost / flt(doc.quantity) : 0;
	}

	calculate_raw_material_cost() {
		let doc = this.frm.doc;

		doc.total_material_cost = 0;
		doc.base_total_material_cost = 0;
		doc.raw_material_cost = 0;
		doc.base_raw_material_cost = 0;
		doc.packaging_material_cost = 0;
		doc.base_packaging_material_cost = 0;
		doc.total_raw_material_qty = 0;

		for (let d of doc.items || []) {
			d.base_rate = flt(d.rate) * flt(doc.conversion_rate);
			d.amount = flt(d.rate) * flt(d.qty);
			d.base_amount = d.amount * flt(doc.conversion_rate);

			d.stock_qty = flt(d.qty) * flt(d.conversion_factor);
			d.qty_consumed_per_unit = doc.quantity ? flt(d.stock_qty) / flt(doc.quantity) : 0;

			let amount_without_op_cost = d.amount - flt(d.child_operating_cost);
			let base_amount_without_op_cost = d.base_amount - flt(d.base_child_operating_cost);

			if (d.is_packaging_material) {
				doc.packaging_material_cost += amount_without_op_cost;
				doc.base_packaging_material_cost += base_amount_without_op_cost;
			} else {
				doc.raw_material_cost += amount_without_op_cost;
				doc.base_raw_material_cost += base_amount_without_op_cost;
			}

			doc.total_material_cost += amount_without_op_cost;
			doc.base_total_material_cost += base_amount_without_op_cost;

			doc.total_raw_material_qty += flt(d.qty);
		}

		doc.unit_material_cost = doc.quantity ? doc.total_material_cost / flt(doc.quantity) : 0;
		doc.base_unit_material_cost = doc.quantity ? doc.base_total_material_cost / flt(doc.quantity) : 0;

		doc.unit_raw_material_cost = doc.quantity ? doc.raw_material_cost / flt(doc.quantity) : 0;
		doc.base_unit_raw_material_cost = doc.quantity ? doc.base_raw_material_cost / flt(doc.quantity) : 0;

		doc.unit_packaging_material_cost = doc.quantity ? doc.packaging_material_cost / flt(doc.quantity) : 0;
		doc.base_unit_packaging_material_cost = doc.quantity ? doc.base_packaging_material_cost / flt(doc.quantity) : 0;

		doc.total_raw_material_qty = flt(doc.total_raw_material_qty, precision("total_raw_material_qty"));
	}

	calculate_scrap_material_cost() {
		let doc = this.frm.doc;

		doc.scrap_material_cost = 0;
		doc.base_scrap_material_cost = 0;

		for (let d of doc.scrap_items || []) {
			d.base_rate = flt(d.rate) * flt(doc.conversion_rate);
			d.amount = flt(d.rate) * flt(d.stock_qty);
			d.base_amount = flt(d.amount) * flt(doc.conversion_rate);

			doc.scrap_material_cost += d.amount;
			doc.base_scrap_material_cost += d.base_amount;
		}

		doc.unit_scrap_material_cost = doc.quantity ? doc.scrap_material_cost / flt(doc.quantity) : 0;
		doc.base_unit_scrap_material_cost = doc.quantity ? doc.base_scrap_material_cost / flt(doc.quantity) : 0;
	}

	make_work_order() {
		const fields = [{
			fieldtype: 'Float',
			label: __('Qty To Produce'),
			fieldname: 'qty',
			reqd: 1,
			default: 1
		}];

		frappe.prompt(fields, data => {
			frappe.call({
				method: "erpnext.manufacturing.doctype.work_order.work_order.make_work_order",
				args: {
					bom_no: this.frm.doc.name,
					item: this.frm.doc.item,
					qty: data.qty || 0.0,
					project: this.frm.doc.project,
				},
				freeze: true,
				callback: (r) => {
					if(r.message) {
						var doc = frappe.model.sync(r.message)[0];
						frappe.set_route("Form", doc.doctype, doc.name);
					}
				}
			});
		}, __("Enter Value"), __("Create"));
	}

	make_quality_inspection() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.quality_inspection.quality_inspection.make_quality_inspection",
			frm: this.frm,
		})
	}
};

extend_cscript(cur_frm.cscript, new erpnext.bom.BomController({frm: cur_frm}));
