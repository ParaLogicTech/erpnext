frappe.provide("erpnext.accounts");

erpnext.accounts.PaymentRequest = class PaymentRequest extends frappe.ui.form.Controller {
	setup() {
		this.setup_queries();
		this.frm.custom_make_buttons = {
			'Payment Entry': 'Payment Entry',
			'Payment Order': 'Payment Order',
		};
	}

	refresh() {
		this.setup_buttons();
		this.setup_dashboard();
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
		if (this.frm.doc.reference_doctype && this.frm.doc.reference_name && !this.frm.doc.__islocal) {
			this.frm.add_custom_button(__('Open {0}', [this.frm.doc.reference_name]), () => {
				frappe.set_route("Form", this.frm.doc.reference_doctype, this.frm.doc.reference_name);
			});
		}

		if (
			this.frm.doc.docstatus == 1
			&& this.frm.doc.payment_request_type == "Inward"
			&& this.frm.doc.status == "Requested"
		) {
			this.frm.add_custom_button(__("Resend Payment Request Notification"), () => this.trigger_payment_request_notification(),
				__("Notify"));
		}

		if (
			this.frm.doc.docstatus == 1
			// && (!this.frm.doc.payment_gateway_account || this.frm.doc.payment_entry_creation_failed)
			&& this.frm.doc.status != "Paid"
		) {
			this.frm.add_custom_button(__('Payment Entry'), () => this.make_payment_entry(),
				__("Create"));
		}
	}

	setup_dashboard() {
		if (this.frm.doc.docstatus == 0) {
			return;
		}

		let payment_link_count = frappe.get_notification_count(this.frm, 'Payment Link');
		let payment_received_count = frappe.get_notification_count(this.frm, 'Payment Received');
		let payment_error_count = frappe.get_notification_count(this.frm, 'Payment Error');

		if (payment_link_count || this.frm.doc.payment_gateway || this.frm.doc.payment_url) {
			let payment_link_color = payment_link_count ? "green" : "light-gray";
			let payment_link_status = frappe.get_notification_count_str(this.frm, 'Payment Link');
			this.frm.dashboard.add_indicator(__('Payment Link: {0}', [payment_link_status]), payment_link_color);
		}

		if (payment_received_count || (this.frm.doc.payment_request_type == "Inward" && this.frm.doc.status == "Paid")) {
			let payment_received_color = payment_received_count ? "green" : "light-gray";
			let payment_received_status = frappe.get_notification_count_str(this.frm, 'Payment Received');
			this.frm.dashboard.add_indicator(__('Payment Received: {0}', [payment_received_status]), payment_received_color);
		}

		if (payment_error_count || this.frm.doc.payment_entry_creation_failed) {
			let payment_error_color = payment_error_count ? "red" : "yellow";
			let payment_error_status = frappe.get_notification_count_str(this.frm, 'Payment Error');
			this.frm.dashboard.add_indicator(__('Payment Error: {0}', [payment_error_status]), payment_error_color);
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
		}, this.frm.doc.payment_request_type == "Inward" ? "incoming" : "outgoing")
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
}

cur_frm.script_manager.make(erpnext.accounts.PaymentRequest);
