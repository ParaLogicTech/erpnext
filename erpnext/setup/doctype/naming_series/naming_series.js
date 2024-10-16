// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt


frappe.ui.form.on("Naming Series", {
	refresh: function(frm) {
		frm.disable_save();
		frm.events.get_doc_and_prefix(frm);
	},

	get_doc_and_prefix: function(frm) {
		frappe.call({
			method: "get_transactions",
			doc: frm.doc,
			freeze: 1,
			callback: function(r) {
				frm.set_df_property("select_doc_for_series", "options", r.message.transactions);
				frm.set_df_property("prefix", "options", r.message.prefixes);
			}
		});
	},

	select_doc_for_series: function(frm) {
		frm.set_value("user_must_always_select", 0);
		frappe.call({
			method: "get_options",
			doc: frm.doc,
			freeze: 1,
			callback: function(r) {
				frm.set_value("set_options", r.message);
				if(r.message && r.message.split('\n')[0]=='')
					frm.set_value('user_must_always_select', 1);
				frm.refresh();
			}
		});
	},

	prefix: function(frm) {
		frm.doc.new_prefix = "";
		frm.refresh_field('new_prefix');
		frm.events.get_current(frm);
	},

	new_prefix: function(frm) {
		frm.events.get_current(frm);
	},

	get_current: function(frm) {
		frappe.call({
			method: "get_current",
			doc: frm.doc,
			freeze: 1,
			callback: function(r) {
				frm.refresh_field("current_value");
			}
		});
	},

	update: function(frm) {
		frappe.call({
			method: "update_series",
			doc: frm.doc,
			freeze: 1,
			callback: function(r) {
				frm.events.get_doc_and_prefix(frm);
			}
		});
	},

	update_series_start: function(frm) {
		frappe.call({
			method: "update_series_start",
			doc: frm.doc,
			freeze: 1,
			callback: function(r) {
				if (!r || !r.message) {
					frm.events.get_current(frm);
				} else {
					frm.events.get_doc_and_prefix(frm);
				}
			}
		});
	}
});
