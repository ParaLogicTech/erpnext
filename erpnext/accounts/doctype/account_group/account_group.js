frappe.ui.form.on('Account Group', {
	refresh(frm) {
		// Set filters for account selection
		frm.set_query('account', 'rows', function(doc, cdt, cdn) {
			let filters = {
				'company': frm.doc.company,
				'root_type': frm.doc.category,
				'is_group': 0
			};

			return { filters };
		});

		// Set filters for account group selection
		frm.set_query('account_group', 'rows', function(doc, cdt, cdn) {
			let filters = {
				'company': frm.doc.company,
				'reporting_type': frm.doc.reporting_type,
			}
			if (!frm.is_new()) {
				filters['name'] = ['!=', frm.doc.name];
			}
			return { filters };
		});
	},
});
