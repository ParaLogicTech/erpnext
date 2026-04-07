// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Mode of Payment", {
	setup(frm) {
		let fields = ["default_account", "default_outgoing_account"];
		for (let child_field of fields) {
			frm.set_query(child_field, "accounts", function(doc, cdt, cdn) {
				let row = frappe.get_doc(cdt, cdn);
				return {
					filters: [
						['Account', 'account_type', 'in', ['Bank', 'Cash']],
						['Account', 'is_group', '=', 0],
						['Account', 'company', '=', row.company],
					]
				}
			});
		}
	}
});
