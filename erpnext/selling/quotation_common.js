frappe.ui.form.on(cur_frm.doctype, {
	transaction_date: function (frm) {
		frm.events.set_valid_till(frm);
	},

	quotation_validity_days: function (frm) {
		frm.events.set_valid_till(frm);
	},

	valid_till: function (frm) {
		frm.events.set_quotation_validity_days(frm);
	},

	set_valid_till: function(frm) {
		if (frm.doc.transaction_date) {
			if (cint(frm.doc.quotation_validity_days) > 0) {
				frm.doc.valid_till = frappe.datetime.add_days(frm.doc.transaction_date, cint(frm.doc.quotation_validity_days)-1);
				frm.refresh_field('valid_till');
			} else if (frm.doc.valid_till && cint(frm.doc.quotation_validity_days) == 0) {
				frm.events.set_quotation_validity_days(frm);
			}
		}
	},

	set_quotation_validity_days: function (frm) {
		if (frm.doc.transaction_date && frm.doc.valid_till) {
			var days = frappe.datetime.get_diff(frm.doc.valid_till, frm.doc.transaction_date) + 1;
			if (days > 0) {
				frm.doc.quotation_validity_days = days;
				frm.refresh_field('quotation_validity_days');
			}
		}
	},

	set_default_quotation_validity: function(frm) {
		if (frm.is_new() && !frm.doc.valid_till && !cint(frm.doc.quotation_validity_days)) {
			if (frappe.boot.sysdefaults.quotation_valid_till) {
				frm.set_value('quotation_validity_days', cint(frappe.boot.sysdefaults.quotation_valid_till));
			} else {
				let valid_till = frappe.datetime.add_months(frm.doc.transaction_date, 1);
				valid_till = frappe.datetime.add_days(valid_till, -1);
				frm.set_value('valid_till', valid_till);
			}
		}
	},

	set_dynamic_field_labels: function(frm) {
		if (frm.doc.quotation_to) {
			frm.set_df_property("party_name", "label", __(frm.doc.quotation_to));
			frm.set_df_property("customer_address", "label", __(frm.doc.quotation_to + " Address"));
		} else {
			frm.set_df_property("party_name", "label", __("Party"));
			frm.set_df_property("customer_address", "label", __("Party Address"));
		}
	}
});
