// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Rename Tool", {
	refresh: function (frm) {
		frm.disable_save();

		frm.get_field("file_to_rename").df.options = {
			restrictions: {
				allowed_file_types: [".csv"],
			},
		};

		frm.page.set_primary_action(__("Rename"), function () {
			frappe.call({
				method: "erpnext.utilities.doctype.rename_tool.rename_tool.upload",
				args: {
					select_doctype: frm.doc.select_doctype,
				},
				freeze: true,
				freeze_message: __("Scheduling..."),
				callback: function () {
					frappe.msgprint({
						message: __("Rename jobs for doctype {0} have been enqueued.", [
							frm.doc.select_doctype,
						]),
						alert: true,
						indicator: "green",
					});
					frm.set_value("select_doctype", "");
					frm.set_value("file_to_rename", "");
				},
				error: function (r) {
					frappe.msgprint({
						message: __("Rename jobs for doctype {0} have not been enqueued.", [
							frm.doc.select_doctype,
						]),
						alert: true,
						indicator: "red",
					});
				},
			});
		});
	}
});