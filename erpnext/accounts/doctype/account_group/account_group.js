frappe.ui.form.on('Account Group', {
	setup(frm) {
		// setup formatters for fieldtype
		frappe.meta.docfield_map["Account Group Row"].row_type.formatter = (value) => {
			const prefix = {
				"Section Total": "--red-600",
				"Section Break": "--blue-600",
				"Formula": "--yellow-600",
			};
			if (prefix[value]) {
				value = `<span class="bold" style="color: var(${prefix[value]})">${value}</span>`;
			}
			return value;
		};
	},

	refresh(frm) {
		// Set filters for account selection
		frm.set_query('account', 'rows', () => {
			let filters = {
				company: frm.doc.company,
				is_group: 0,
			};

            if (frm.doc.report_type != "Cash Flow") {
				filters["report_type"] = frm.doc.report_type;
            }

			return { filters };
		});

		// Set filters for account group selection
		frm.set_query('account_group', 'rows', () => {
            let filters = {
                company: frm.doc.company,
            };

            if (frm.doc.report_type != "Cash Flow") {
				filters["report_type"] = frm.doc.report_type;
            }

            if (!frm.is_new()) {
                filters["name"] = ['!=', frm.doc.name];
            }

			return {
				query: "erpnext.accounts.doctype.account_group.account_group.account_group_query",
				filters: filters,
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
