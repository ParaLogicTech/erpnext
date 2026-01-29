// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.query_reports["Stock Projected Qty"] = {
	"filters": [
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company")
		},
		{
			"fieldname":"qty_field",
			"label": __("Stock Qty or Contents Qty"),
			"fieldtype": "Select",
			"options": "Stock Qty\nContents Qty",
			"default": "Stock Qty"
		},
		{
			"fieldname":"warehouse",
			"label": __("Warehouse"),
			"fieldtype": "Link",
			"options": "Warehouse"
		},
		{
			"fieldname":"item_code",
			"label": __("Item"),
			"fieldtype": "Link",
			"options": "Item",
			"get_query": function() {
				return {
					query: "erpnext.controllers.queries.item_query",
					filters: {'include_disabled': 1, 'include_templates':1}
				}
			}
		},
		{
			"fieldname":"item_group",
			"label": __("Item Group"),
			"fieldtype": "Link",
			"options": "Item Group"
		},
		{
			"fieldname":"brand",
			"label": __("Brand"),
			"fieldtype": "Link",
			"options": "Brand"
		},
		{
			"fieldname":"include_uom",
			"label": __("Include UOM"),
			"fieldtype": "Link",
			"options": "UOM"
		},
		{
			fieldname: "customer_provided_items",
			label: __("Customer Provided Items"),
			fieldtype: "Select",
			options: [
				"",
				"Customer Provided Items Only",
				"Exclude Customer Provided Items",
			]
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "group_by_1",
			label: __("Group By Level 1"),
			fieldtype: "Select",
			options: ["", "Group by Item", "Group by Warehouse", "Group by Item Group", "Group by Brand"],
			default: ""
		},
		{
			fieldname: "group_by_2",
			label: __("Group By Level 2"),
			fieldtype: "Select",
			options: ["", "Group by Item", "Group by Warehouse", "Group by Item Group", "Group by Brand"],
			default: ""
		},
	],
	formatter: function(value, row, column, data, default_formatter) {
		let options = {
			css: {},
			link_target: "_blank",
		};

		if (['actual_qty', 'projected_qty', 'shortage_qty'].includes(column.fieldname)) {
			if (flt(value) < 0) {
				options.css['background-color'] = 'pink';
				options.css['font-weight'] = 'bold';
			}
		}

		if (['projected_qty', 'ordered_qty', 'planned_qty', 'indented_qty'].includes(column.fieldname)) {
			if (flt(value) > 0) {
				options.css['color'] = 'var(--green-700)';
			} else if(flt(value) < 0 && column.fieldname !== 'projected_qty') {
				options.css['color'] = 'var(--red-500)';
			}
		}

		if (['reserved_qty', 'reserved_qty_for_production', 'reserved_qty_for_sub_contract'].includes(column.fieldname)) {
			if (flt(value) > 0) {
				options.css['color'] = 'var(--red-500)';
			} else if(flt(value) < 0) {
				options.css['color'] = 'var(--green-700)';
			}
		}

		// URLS
		let params = {};
		if (data?.item_code) {
			params["item_code"] = data.item_code;
			if (data.warehouse) {
				params["warehouse"] = data.warehouse;
			}
			const query_string = Object.entries(params)
				.map(([key, val]) => `${key}=${encodeURIComponent(val)}`)
				.join('&');

			if (column.fieldname == "actual_qty") {
				options.link_href = `/app/query-report/Stock Balance?${query_string}`;
			}

			if (column.fieldname == "reserved_qty") {
				options.link_href = `/app/query-report/Sales Items To Be Delivered?${query_string}`;
			}

			if (column.fieldname == "ordered_qty") {
				options.link_href = `/app/query-report/Purchase Items To Be Received?${query_string}`;
			}
		}

		return default_formatter(value, row, column, data, options);
	},
	"initial_depth": 0
}

erpnext.utils.add_additional_sle_filters("Stock Projected Qty");
