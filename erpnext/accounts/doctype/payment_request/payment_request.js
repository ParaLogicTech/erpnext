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
