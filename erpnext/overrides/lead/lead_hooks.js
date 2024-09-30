frappe.provide("crm");

crm.LeadControllerERP = class LeadControllerERP extends crm.LeadController {
	setup() {
		super.setup();
		Object.assign(this.frm.custom_make_buttons, {
			'Customer': 'Customer',
			'Quotation': 'Quotation',
			'Vehicle Quotation': 'Vehicle Quotation',
		});
	}

	setup_buttons() {
		if (!this.frm.doc.__islocal) {
			if (!this.frm.doc.customer) {
				this.frm.add_custom_button(__("Customer"), () => this.make_or_set_customer(),
					__('Create'));

				if (frappe.boot.active_domains.includes("Vehicles")) {
					this.frm.add_custom_button(__("Vehicle Quotation"), () => this.make_vehicle_quotation(),
						__('Create'));
				}

				this.frm.add_custom_button(__("Quotation"), () => this.make_quotation(),
					__('Create'));
			} else {
				this.frm.add_custom_button(__("Customer"), () => this.make_or_set_customer(),
					__("Change"));
			}
		}

		super.setup_buttons();
	}

	make_or_set_customer() {
		erpnext.utils.make_customer_from_lead(this.frm, this.frm.doc.name);
	}

	make_quotation() {
		frappe.model.open_mapped_doc({
			method: "erpnext.overrides.lead.lead_hooks.make_quotation",
			frm: this.frm
		})
	}

	make_vehicle_quotation() {
		frappe.model.open_mapped_doc({
			method: "erpnext.overrides.lead.lead_hooks.make_vehicle_quotation",
			frm: this.frm
		})
	}
}

extend_cscript(cur_frm.cscript, new crm.LeadControllerERP({ frm: cur_frm }));
