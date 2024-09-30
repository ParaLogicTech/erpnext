frappe.ui.form.on('Sales Person', {
	setup: function(frm) {
		frm.fields_dict["targets"].grid.get_field("distribution_id").get_query = function(doc, cdt, cdn){
			let row = locals[cdt][cdn];
			return {
				filters: {
					'fiscal_year': row.fiscal_year
				}
			}
		};

		frm.make_methods = {
			'Sales Order': () => {
				frappe.new_doc("Sales Order").then(() => {
					frm.add_child("sales_team", {"sales_person": frm.doc.name})
				});
			}
		}

		frm.set_query("employee", () => {
			return {
				query: "erpnext.controllers.queries.employee_query"
			}
		});
	},

	refresh: function(frm) {
		if(frm.doc.__onload && frm.doc.__onload.dashboard_info) {
			var info = frm.doc.__onload.dashboard_info;
			frm.dashboard.add_indicator(__('Total Contribution Amount: {0}',
				[format_currency(info.allocated_amount, info.currency)]), 'green');
			frm.dashboard.add_indicator(__('Total Contribution Stock Qty: {0}',
				[frappe.format(info.allocated_stock_qty, {'fieldtype': 'Float'}, {'inline': 1})]), 'blue');
			frm.dashboard.add_indicator(__('Total Contribution Contents Qty: {0}',
				[frappe.format(info.allocated_alt_uom_qty, {'fieldtype': 'Float'}, {'inline': 1})]), 'purple');
		}

		frm.events.set_employee_fields_read_only(frm);
	},

	employee: function (frm) {
		frm.events.set_employee_fields_read_only(frm);
		return frappe.call({
			method: "erpnext.overrides.sales_person.sales_person_hooks.get_employee_details",
			args: {
				employee: frm.doc.employee,
			},
			callback: (r) => {
				if (r.message) {
					frm.set_value(r.message);
				}
			}
		});
	},

	set_employee_fields_read_only: function (frm) {
		let read_only = cint(Boolean(frm.doc.employee));
		frm.set_df_property("user_id", "read_only", read_only);
		frm.set_df_property("contact_email", "read_only", read_only);
		frm.set_df_property("contact_mobile", "read_only", read_only);
	}
});
