// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Product Bundle", {
	refresh(frm) {
		frm.set_query("new_item_code", () => {
			return erpnext.queries.item({
				is_stock_item: 0,
				is_fixed_asset: 0,
				has_product_bundle: 0,
			})
		});

		frm.set_query("item_code", "items", () => {
			return erpnext.queries.item({
				has_product_bundle: 0,
			});
		});
	}
});
