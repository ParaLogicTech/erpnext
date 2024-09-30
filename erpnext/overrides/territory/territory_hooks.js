frappe.ui.form.on("Territory", {
	setup: function(frm) {
		frm.fields_dict["targets"].grid.get_field("distribution_id").get_query = function(doc, cdt, cdn){
			var row = locals[cdt][cdn];
			return {
				filters: {
					'fiscal_year': row.fiscal_year
				}
			}
		};
	}
});
