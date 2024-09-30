frappe.listview_settings['Appointment'].base_onload = frappe.listview_settings['Appointment'].onload;

frappe.listview_settings['Appointment'].onload = function(listview) {
	frappe.listview_settings['Appointment'].base_onload(listview);

	if (listview.page.fields_dict.applies_to_variant_of) {
			listview.page.fields_dict.applies_to_variant_of.get_query = () => {
				return erpnext.queries.item({"has_variants": 1, "include_disabled": 1});
			}
		}

		if (listview.page.fields_dict.applies_to_item) {
			listview.page.fields_dict.applies_to_item.get_query = () => {
				var variant_of = listview.page.fields_dict.applies_to_variant_of.get_value('applies_to_variant_of');
				var filters = {"include_disabled": 1};
				if (variant_of) {
					filters['variant_of'] = variant_of;
				}
				return erpnext.queries.item(filters);
			}
		}
};
