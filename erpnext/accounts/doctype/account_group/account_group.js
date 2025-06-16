frappe.ui.form.on('Account Group', {
	refresh(frm) {
		// Set filters for account selection
		frm.set_query('account', 'rows', function(doc, cdt, cdn) {
			let filters = {
				'company': frm.doc.company,
				'report_type': frm.doc.report_type,
				'is_group': 0
			};

			return { filters };
		});

		// Set filters for account group selection
		frm.set_query('account_group', 'rows', function(doc, cdt, cdn) {
			return {
				query: "erpnext.accounts.doctype.account_group.account_group.get_account_groups_for_balance_sheet",
				filters: {
					company: frm.doc.company,
					report_type: frm.doc.report_type,
					exclude_name: frm.doc.name
				}
			};
		});

		let account_group_field = frm.get_docfield("rows", "account_group");
		if (account_group_field) {
			account_group_field.get_route_options_for_new_doc = function(row) {
				return {
					"company": frm.doc.company,
					"report_type": frm.doc.report_type,
					"root_type": frm.doc.root_type,
				}
			};
		}
	},
});
