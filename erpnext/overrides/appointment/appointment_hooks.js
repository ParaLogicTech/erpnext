frappe.provide("crm");

{% include 'erpnext/vehicles/customer_vehicle_selector.js' %};

crm.AppointmentERP = class AppointmentERP extends crm.Appointment {
	setup() {
		super.setup();

		erpnext.setup_applies_to_fields(this.frm);

		Object.assign(this.frm.custom_make_buttons, {
			"Project": "Project",
		});
	}

	refresh() {
		erpnext.hide_company();
		super.refresh();
		this.make_customer_vehicle_selector();
	}

	setup_queries() {
		super.setup_queries();

		this.frm.set_query("party_name", () => {
			if (this.frm.doc.appointment_for === "Customer") {
				return erpnext.queries.customer();
			} else if (this.frm.doc.appointment_for === "Lead") {
				return crm.queries.lead({"status": ["!=", "Converted"]});
			}
		});

		this.frm.set_query("project_template", () => {
			return erpnext.queries.project_template(this.frm.doc.applies_to_item);
		});
	}

	setup_buttons() {
		super.setup_buttons();

		if (this.frm.doc.docstatus == 1 && this.frm.doc.status != "Rescheduled") {
			let customer;
			if (this.frm.doc.appointment_for == "Customer") {
				customer = this.frm.doc.party_name;
			} else if (this.frm.doc.appointment_for == "Lead") {
				customer = this.frm.doc.__onload && this.frm.doc.__onload.customer;
			}

			if (!customer) {
				this.frm.add_custom_button(__('Customer'), () => {
					erpnext.utils.make_customer_from_lead(this.frm, this.frm.doc.party_name);
				}, __('Create'));
			}

			this.frm.add_custom_button(__('Project'), () => this.make_project(), __('Create'));
			this.frm.page.set_inner_btn_group_as_primary(__('Create'));
		}
	}

	appointment_for() {
		super.appointment_for();
		this.reload_customer_vehicle_selector();
	}

	party_name() {
		super.party_name();
		this.reload_customer_vehicle_selector();
	}

	make_customer_vehicle_selector() {
		if (this.frm.fields_dict.customer_vehicle_selector_html) {
			this.frm.customer_vehicle_selector = erpnext.vehicles.make_customer_vehicle_selector(this.frm,
				this.frm.fields_dict.customer_vehicle_selector_html.wrapper,
				'applies_to_vehicle',
				'party_name',
				'appointment_for'
			);
		}
	}

	reload_customer_vehicle_selector() {
		if (this.frm.customer_vehicle_selector) {
			this.frm.customer_vehicle_selector.load_and_render();
		}
	}

	applies_to_vehicle() {
		this.reload_customer_vehicle_selector();
	}

	vehicle_chassis_no() {
		erpnext.utils.format_vehicle_id(this.frm, 'vehicle_chassis_no');
	}
	vehicle_engine_no() {
		erpnext.utils.format_vehicle_id(this.frm, 'vehicle_engine_no');
	}
	vehicle_license_plate() {
		erpnext.utils.format_vehicle_id(this.frm, 'vehicle_license_plate');
	}

	make_project() {
		this.frm.check_if_unsaved();
		frappe.model.open_mapped_doc({
			method: "erpnext.overrides.appointment.appointment_hooks.get_project",
			frm: this.frm
		});
	}
}

extend_cscript(cur_frm.cscript, new crm.AppointmentERP({ frm: cur_frm }));
