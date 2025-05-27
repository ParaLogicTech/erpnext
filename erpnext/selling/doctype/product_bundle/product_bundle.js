// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

cur_frm.cscript.refresh = function(doc, cdt, cdn) {
	cur_frm.toggle_enable('new_item_code', doc.__islocal);
}

cur_frm.fields_dict.new_item_code.get_query = function() {
	return{
		query: "erpnext.selling.doctype.product_bundle.product_bundle.get_new_item_code"
	}
}
cur_frm.fields_dict.new_item_code.query_description = __('Please select Item where "Is Stock Item" is "No" and "Is Sales Item" is "Yes" and there is no other Product Bundle');

cur_frm.cscript.onload = function() {
	// set add fetch for item_code's item_name and description
	cur_frm.add_fetch('item_code', 'stock_uom', 'uom');
	cur_frm.add_fetch('item_code', 'description', 'description');
}

// Add helper function for Item Group selection
frappe.ui.form.on('Product Bundle Item', {
	type: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.type === 'Item Group') {
			// Clear item_code when switching to Item Group
			row.item_code = '';
			refresh_field('items');
		}
	},
	
	item_group: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.type === 'Item Group' && row.item_group) {
			// Show dialog to select items from group
			frappe.prompt({
				fieldname: 'items',
				fieldtype: 'MultiSelect',
				label: __('Select Items from Group'),
				options: frappe.db.get_list('Item', {
					filters: {
						item_group: row.item_group,
						is_stock_item: 1
					},
					fields: ['name', 'item_name']
				}).map(d => ({label: d.item_name, value: d.name})),
				reqd: 1
			}, function(values) {
				row.selected_items = values.items;
				refresh_field('items');
			}, __('Select Items'), __('Select'));
		}
	}
});
