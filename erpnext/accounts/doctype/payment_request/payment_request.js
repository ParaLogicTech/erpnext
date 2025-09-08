frappe.provide("erpnext.accounts");

erpnext.accounts.PaymentRequest = class PaymentRequest extends frappe.ui.form.Controller {
	setup() {
		this.setup_queries();
	}

	refresh() {
		this.setup_buttons();
		this.get_print_format_list();
	}

	setup_queries() {
		this.frm.set_query("party_type", () => {
			return {
				query: "erpnext.setup.doctype.party_type.party_type.get_party_type",
			};
		});

		this.frm.set_query("payment_account", () => {
			return {
				filters: {
					"account_type": ["in", ["Bank", "Cash"]],
					"is_group": 0,
					"company": this.frm.doc.company
				}
			}
		});

		this.frm.set_query("pos_profile", (doc) => {
			if (!doc.company) {
				frappe.throw(__('Please set Company'));
			}

			let filters = {
				company: doc.company,
			}
			if (doc.branch) {
				filters["branch"] = doc.branch;
			}
			if (doc.user) {
				filters["user"] = doc.owner || frappe.session.user;
			}

			return {
				query: "erpnext.accounts.doctype.pos_profile.pos_profile.pos_profile_query",
				filters: filters,
			};
		});
	}

	setup_buttons() {
		if (
			this.frm.doc.docstatus == 1
			&& this.frm.doc.payment_request_type == "Inward"
			&& this.frm.doc.status != "Paid"
		) {
			this.frm.add_custom_button(__("Resend Payment Request Notification"), () => this.trigger_payment_request_notification(),
				__("Notify"));
		}

		if (
			this.frm.doc.docstatus == 1
			&& !this.frm.doc.payment_gateway_account
			&& this.frm.doc.status == "Initiated"
		) {
			this.frm.add_custom_button(__('Payment Entry'), () => this.make_payment_entry(),
				__("Create"));
		}
	}

	trigger_payment_request_notification() {
		return frappe.call({
			method: "erpnext.accounts.doctype.payment_request.payment_request.trigger_payment_request_notification",
			args: {
				"payment_request": this.frm.doc.name
			},
			freeze: true,
			freeze_message: __("Sending"),
			callback: (r) =>{
				if (!r.exc) {
					frappe.msgprint(__("Notification Triggered"));
				}
			}
		});
	}

	payment_gateway_account() {
		return frappe.call({
			method: "erpnext.accounts.doctype.payment_request.payment_request.get_payment_gateway_account_details",
			args: {
				"payment_gateway_account": this.frm.doc.payment_gateway_account
			},
			callback: (r) => {
				if (r.message) {
					this.frm.set_value(r.message);
				}
			}
		});
	}

	is_pos() {
		this.set_pos_data();
	}

	pos_profile() {
		this.set_pos_data();
	}

	set_pos_data() {
		if (this.frm.doc.is_pos) {
			if (!this.frm.doc.company) {
				this.frm.set_value("is_pos", 0);
				frappe.msgprint(__("Please specify Company to proceed"));
			} else {
				return this.frm.call({
					doc: this.frm.doc,
					method: "set_missing_values",
					freeze: 1,
					callback: (r) => {
						if (!r.exc) {
							frappe.model.set_default_values(this.frm.doc);
						}
					}
				});
			}
		}
	}

	mode_of_payment() {
		erpnext.utils.get_payment_mode_account(this.frm, this.frm.doc.mode_of_payment, (account) => {
			this.frm.set_value("payment_account", account);
		})
	}

	make_payment_entry() {
		return frappe.call({
			method: "erpnext.accounts.doctype.payment_request.payment_request.make_payment_entry",
			args: {
				"payment_request": this.frm.doc.name
			},
			freeze: true,
			callback: (r) => {
				if (r.message) {
					frappe.model.sync(r.message);
					frappe.set_route("Form", r.message.doctype, r.message.name);
				}
			}
		});
	}

	get_print_format_list() {
		if (this.frm.doc.reference_doctype && this.frm.doc.docstatus == 0) {
			return frappe.call({
				method: "erpnext.accounts.doctype.payment_request.payment_request.get_print_format_list",
				args: {
					"reference_doctype": this.frm.doc.reference_doctype,
				},
				callback: (r) => {
					set_field_options("print_format", r.message["print_format"]);
				}
			})
		}
	}
}

cur_frm.script_manager.make(erpnext.accounts.PaymentRequest);
