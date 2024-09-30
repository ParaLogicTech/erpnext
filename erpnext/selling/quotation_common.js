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
})
