frappe.provide("erpnext");

erpnext.OpportunityERP = class OpportunityERP extends crm.Opportunity {
	setup() {
		super.setup();
		erpnext.setup_applies_to_fields(this.frm);

		Object.assign(this.frm.custom_make_buttons, {
			'Customer': 'Customer',
			'Quotation': 'Quotation',
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

		this.frm.set_query("uom", "items", function(doc, cdt, cdn) {
			let item = frappe.get_doc(cdt, cdn);
			return erpnext.queries.item_uom(item.item_code);
		});

		this.frm.set_query("service_template", "service_templates", () => {
			return erpnext.queries.service_template(this.frm.doc.applies_to_item);
		});
	}

	setup_buttons() {
		super.setup_buttons();

		if (!this.frm.doc.__islocal && this.frm.doc.status !== "Lost") {
			if (!this.frm.doc.__onload.customer) {
				this.frm.add_custom_button(__('Customer'), () => this.create_customer(),
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

	service_template(doc, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		this.get_service_template_details(row);
	}

	get_service_template_details(row) {
		if (row && row.service_template) {
			let args = this.get_service_template_args(row);

			return frappe.call({
				method: "erpnext.projects.doctype.service_template.service_template.get_service_template_details",
				args: {
					service_template: row.service_template,
					args: args,
				},
				callback: (r) => {
					if (r.message) {
						frappe.model.set_value(row.doctype, row.name, r.message);
					}
				}
			});
		}
	}

	get_service_template_args(row) {
		return {
			customer: this.frm.doc.opportunity_from == "Customer" ? this.frm.doc.party_name : null,
			applies_to_item: this.frm.doc.applies_to_item,
			date: this.frm.doc.transaction_date,
		}
	}

	add_service_template(service_template, check_duplicate) {
		return erpnext.utils.add_service_template_row(this.frm, service_template, check_duplicate);
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

	make_supplier_quotation() {
		frappe.model.open_mapped_doc({
			method: "erpnext.overrides.opportunity.opportunity_hooks.make_supplier_quotation",
			frm: this.frm
		});
	}
}

extend_cscript(cur_frm.cscript, new erpnext.OpportunityERP({ frm: cur_frm }));
