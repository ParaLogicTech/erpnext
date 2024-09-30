frappe.ui.form.on("Communication", {
	refresh: (frm) => {
		// setup custom Make button only if Communication is Email
		if(frm.doc.communication_medium == "Email" && frm.doc.sent_or_received == "Received") {
			frm.events.setup_support_buttons(frm);
		}
	},

	setup_support_buttons: (frm) => {
		let confirm_msg = "Are you sure you want to create {0} from this email?";
		if(frm.doc.reference_doctype !== "Issue") {
			frm.add_custom_button(__("Issue"), () => {
				frappe.confirm(__(confirm_msg, [__("Issue")]), () => {
					frm.trigger('make_issue_from_communication');
				})
			}, "Create");
		}
	},

	make_issue_from_communication: (frm) => {
		return frappe.call({
			method: "erpnext.support.doctype.issue.issue.make_issue_from_communication",
			args: {
				communication: frm.doc.name
			},
			freeze: true,
			callback: (r) => {
				if(r.message) {
					frm.reload_doc()
				}
			}
		})
	},
});
