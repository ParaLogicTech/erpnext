// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Accounts Settings', {
	refresh: function(frm) {
		let exchange_rate_providers = frm.doc.__onload?.exchange_rate_providers || [];
		exchange_rate_providers = [""].concat(exchange_rate_providers);

		frm.set_df_property(
			"default_currency_exchange_provider",
			"options",
			exchange_rate_providers,
		);
	}
});
