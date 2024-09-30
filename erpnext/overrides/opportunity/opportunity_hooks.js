frappe.provide("crm");

crm.OpportunityERP = class OpportunityERP extends crm.Opportunity {
	setup() {
		super.setup();
		erpnext.setup_applies_to_fields(this.frm);

		Object.assign(this.frm.custom_make_buttons, {
			'Customer': 'Customer',
			'Quotation': 'Quotation',
			'Vehicle Quotation': 'Vehicle Quotation',
			'Vehicle Booking Order': 'Vehicle Booking Order',
			'Vehicle Gate Pass': 'Test Drive Gate Pass',
			'Supplier Quotation': 'Supplier Quotation',
		});
	}

	refresh() {
		erpnext.hide_company();
		super.refresh();
	}

	onload_post_render() {
		this.frm.get_field("items").grid.set_multiple_add("item_code", "qty");
	}

	setup_queries() {
		super.setup_queries();

		this.frm.set_query('party_name', () => {
			if (this.frm.doc.appointment_for === "Customer") {
				return erpnext.queries.customer();
			} else if (this.frm.doc.appointment_for === "Lead") {
				return crm.queries.lead({"status": ["!=", "Converted"]});
			}
		});

		this.frm.set_query("item_code", "items", () => {
			return {
				query: "erpnext.controllers.queries.item_query",
				filters: {'is_sales_item': 1}
			};
		});

		if (this.frm.fields_dict.delivery_period) {
			this.frm.set_query("delivery_period", () => {
				if (this.frm.doc.transaction_date) {
					return {
						filters: {to_date: [">=", this.frm.doc.transaction_date]}
					}
				}
			});
		}
	}

	setup_buttons() {
		super.setup_buttons();

		if (!this.frm.doc.__islocal && this.frm.doc.status !== "Lost") {
			if (!this.frm.doc.__onload.customer) {
				this.frm.add_custom_button(__('Customer'), () => this.create_customer(),
					__('Create'));
			}

			if (
				frappe.boot.active_domains.includes("Vehicles")
				&& (!this.frm.doc.conversion_document || this.frm.doc.conversion_document == "Order")
			) {
				this.frm.add_custom_button(__("Vehicle Booking Order"), () => this.make_vehicle_booking_order(),
					__('Create'));

				this.frm.add_custom_button(__("Vehicle Quotation"), () => this.make_vehicle_quotation(),
					__('Create'));

				this.frm.add_custom_button(__("Test Drive Gate Pass"), () => this.make_opportunity_gate_pass(),
					__('Create'));
			}

			this.frm.add_custom_button(__('Quotation'), () => this.create_quotation(),
				__('Create'));

			if (this.frm.doc.items && this.frm.doc.items.length) {
				this.frm.add_custom_button(__('Supplier Quotation'), () => this.make_supplier_quotation(),
					__('Create'));
			}
		}
	}

	update_dynamic_fields() {
		super.update_dynamic_fields();

		let vehicle_sales_fields = [
			"vehicle_sb_1",
			"vehicle_sb_2",
			"feedback_section",
			"ratings_section",
			"previously_owned_section"
		];

		for (let field of vehicle_sales_fields) {
			this.frm.toggle_display(field, this.frm.doc.conversion_document == "Order");
		}

		let vehicle_maintenance_fields = [
			"due_date",
			"applies_to_vehicle",
			"vehicle_license_plate",
			"vehicle_unregistered",
			"vehicle_chassis_no",
			"vehicle_engine_no",
			"vehicle_last_odometer",
		]

		$.each(vehicle_maintenance_fields, (i, f) => {
			if (this.frm.fields_dict[f]) {
				this.frm.set_df_property(f, "hidden", this.frm.doc.conversion_document == "Order" ? 1 : 0);
			}
		});
	}

	item_code(doc, cdt, cdn) {
		let d = frappe.get_doc(cdt, cdn);

		if (d.item_code) {
			return frappe.call({
				method: "erpnext.overrides.opportunity.opportunity_hooks.get_item_details",
				args: {
					"item_code": d.item_code
				},
				callback: (r) => {
					if(r.message) {
						$.each(r.message, (k, v) => {
							frappe.model.set_value(cdt, cdn, k, v);
						});
					}
				}
			});
		}
	}

	create_customer() {
		erpnext.utils.make_customer_from_lead(this.frm, this.frm.doc.party_name);
	}

	create_quotation() {
		frappe.model.open_mapped_doc({
			method: "erpnext.overrides.opportunity.opportunity_hooks.make_quotation",
			frm: this.frm
		});
	}

	make_vehicle_quotation() {
		frappe.model.open_mapped_doc({
			method: "erpnext.overrides.opportunity.opportunity_hooks.make_vehicle_quotation",
			frm: this.frm
		});
	}

	make_opportunity_gate_pass() {
		return frappe.call ({
			method: "erpnext.overrides.opportunity.opportunity_hooks.make_opportunity_gate_pass",
			args :{
				"opportunity": this.frm.doc.name,
			},
			callback: (r) => {
				if (!r.exc) {
					let doclist = frappe.model.sync(r.message);
					frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				}
			}
		});
	}

	make_vehicle_booking_order() {
		frappe.model.open_mapped_doc({
			method: "erpnext.overrides.opportunity.opportunity_hooks.make_vehicle_booking_order",
			frm: this.frm
		});
	}

	make_supplier_quotation() {
		frappe.model.open_mapped_doc({
			method: "erpnext.overrides.opportunity.opportunity_hooks.make_supplier_quotation",
			frm: this.frm
		});
	}
}

extend_cscript(cur_frm.cscript, new crm.OpportunityERP({ frm: cur_frm }));
