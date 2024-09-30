// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

const group_by_options_gp = [
	"", "Group by Invoice", "Group by Customer", "Group by Customer Group",
	"Group by Item", "Group by Item Group", "Group by Brand", "Group by Warehouse",
	"Group by Territory", "Group by Sales Person", "Group by Item Source",
	"Group by Applies To Item", "Group by Applies To Variant Of",
	"Group by Transaction Type", "Group by Project", "Group by Cost Center"
]

frappe.query_reports["Gross Profit"] = {
	"filters": [
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"reqd": 1,
			"default": frappe.defaults.get_user_default("Company")
		},
		{
			"fieldname":"from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			"reqd": 1
		},
		{
			"fieldname":"to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"reqd": 1
		},
		{
			"fieldname":"sales_invoice",
			"label": __("Sales Invoice"),
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"filters": {
				"docstatus": 1,
				"is_return": 0,
				"is_opening": ["!=", "Yes"]
			}
		},
		{
			"fieldname":"customer",
			"label": __("Customer"),
			"fieldtype": "Link",
			"options": "Customer"
		},
		{
			"fieldname":"customer_group",
			"label": __("Customer Group"),
			"fieldtype": "Link",
			"options": "Customer Group"
		},
		{
			"fieldname":"territory",
			"label": __("Territory"),
			"fieldtype": "Link",
			"options": "Territory"
		},
		{
			"fieldname":"sales_person",
			"label": __("Sales Person"),
			"fieldtype": "Link",
			"options": "Sales Person"
		},
		{
			"fieldname":"item_code",
			"label": __("Item"),
			"fieldtype": "Link",
			"options": "Item",
			"get_query": function() {
				return {
					query: "erpnext.controllers.queries.item_query",
					filters: {'include_disabled': 1, 'include_templates': 1}
				};
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
			"fieldname":"warehouse",
			"label": __("Warehouse"),
			"fieldtype": "Link",
			"options": "Warehouse"
		},
		{
			"fieldname":"batch_no",
			"label": __("Batch"),
			"fieldtype": "Link",
			"options": "Batch"
		},
		{
			"fieldname":"item_source",
			"label": __("Item Source"),
			"fieldtype": "Link",
			"options": "Item Source"
		},
		{
			fieldname: "applies_to_item",
			label: __("Applies to Item"),
			fieldtype: "Link",
			options: "Item",
			get_query: function() {
				return {
					query: "erpnext.controllers.queries.item_query",
					filters: {'include_disabled': 1,'include_templates':1}
				}
			},
		},
		{
			"fieldname":"transaction_type",
			"label": __("Transaction Type"),
			"fieldtype": "Link",
			"options": "Transaction Type"
		},
		{
			"fieldname":"project",
			"label": __("Project"),
			"fieldtype": "Link",
			"options": "Project"
		},
		{
			"fieldname":"cost_center",
			"label": __("Cost Center"),
			"fieldtype": "Link",
			"options": "Cost Center"
		},
		{
			fieldname: "include_non_stock_items",
			label: __("Include Non Stock Items"),
			fieldtype: "Check",
		},
		{
			fieldname: "group_by_1",
			label: __("Group By Level 1"),
			fieldtype: "Select",
			options: group_by_options_gp,
			default: ""
		},
		{
			fieldname: "group_by_2",
			label: __("Group By Level 2"),
			fieldtype: "Select",
			options: group_by_options_gp,
			default: ""
		},
		{
			fieldname: "group_by_3",
			label: __("Group By Level 3"),
			fieldtype: "Select",
			options: group_by_options_gp,
			default: ""
		},
		{
			fieldname: "totals_only",
			label: __("Group Totals Only"),
			fieldtype: "Check",
			default: 0
		},
	],
	formatter: function(value, row, column, data, default_formatter) {
		var style = {};

		if (['gross_profit', 'gross_profit_per_unit', 'profit_margin', 'profit_markup'].includes(column.fieldname)) {
			if (flt(value, 2) === 0) {
				style['color'] = 'orange';
			} else if (flt(value) < 0) {
				style['color'] = 'red';
			}
		}

		if (['gross_profit'].includes(column.fieldname)) {
			style['font-weight'] = 'bold';
		}

		return default_formatter(value, row, column, data, {css: style});
	},
	get_datatable_options(options) {
		return Object.assign(options, {
			hooks: {
				columnTotal: function (values, column, type) {
					if (in_list(['gross_profit_per_unit', 'profit_margin', 'profit_markup', 'valuation_rate', 'cogs_per_unit'], column.column.fieldname)) {
						return '';
					} else {
						return frappe.utils.report_column_total(values, column, type);
					}
				}
			},
		});
	},
	"initial_depth": 1,
}
