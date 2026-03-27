frappe.provide("erpnext");

erpnext.AppointmentERP = class AppointmentERP extends crm.Appointment {
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

		this.frm.set_query("service_template", "service_templates", () => {
			return erpnext.queries.service_template(this.frm.doc.applies_to_item);
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

			if (frappe.model.can_create("Project")) {
				this.frm.add_custom_button(__('Project'), () => this.make_project(),
					__('Create'));
			}

			if (this.frm.page.get_inner_group_button(__("Create")).length) {
				this.frm.page.set_inner_btn_group_as_primary(__('Create'));
			}
		}
	}

	make_project() {
		this.frm.check_if_unsaved();
		frappe.model.open_mapped_doc({
			method: "erpnext.overrides.appointment.appointment_hooks.get_project",
			frm: this.frm
		});
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
			customer: this.frm.doc.appointment_for == "Customer" ? this.frm.doc.party_name : null,
			applies_to_item: this.frm.doc.applies_to_item,
			date: this.frm.doc.scheduled_date,
		}
	}

	add_service_template(service_template, check_duplicate) {
		return erpnext.utils.add_service_template_row(this.frm, service_template, check_duplicate);
	}
}

extend_cscript(cur_frm.cscript, new erpnext.AppointmentERP({ frm: cur_frm }));
