// Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.provide("erpnext.stock");

erpnext.stock.PackageTypeController = class PackageTypeController extends erpnext.stock.PackingController {
	item_table_fields = ['packaging_items']

	setup() {
		this.setup_queries();
	}

	setup_queries() {
		this.setup_warehouse_query();

		this.frm.set_query("item_code", "packaging_items", function() {
			return erpnext.queries.item({is_stock_item: 1});
		});

		this.frm.set_query("uom", "packaging_items", (doc, cdt, cdn) => {
			let item = frappe.get_doc(cdt, cdn);
			return erpnext.queries.item_uom(item.item_code);
		});
	}

	calculate_totals() {
		this.frm.doc.total_tare_weight = 0;

		for (let item of this.frm.doc.packaging_items || []) {
			frappe.model.round_floats_in(item, null, ['tare_weight_per_unit']);
			item.stock_qty = flt(item.qty * item.conversion_factor, 6);
			item.tare_weight = flt(item.tare_weight_per_unit * item.stock_qty, precision("tare_weight", item));

			this.frm.doc.total_tare_weight += item.tare_weight;
		}

		frappe.model.round_floats_in(this.frm.doc, ['total_tare_weight']);

		this.frm.refresh_fields();
	}

	length() {
		this.calculate_volume();
	}
	width() {
		this.calculate_volume();
	}
	height() {
		this.calculate_volume();
	}
	volume_based_on() {
		this.calculate_volume();
	}

	calculate_volume() {
		if (this.frm.doc.volume_based_on == "Dimensions") {
			frappe.model.round_floats_in(this.frm.doc, ['length', 'width', 'height']);
			this.frm.doc.volume = flt(this.frm.doc.length * this.frm.doc.width * this.frm.doc.height,
				precision("volume"));
			this.frm.refresh_field("volume");
		}
	}
};

extend_cscript(cur_frm.cscript, new erpnext.stock.PackageTypeController({frm: cur_frm}));
