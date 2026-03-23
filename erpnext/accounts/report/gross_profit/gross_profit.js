// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

const group_by_options_gp = [
	"",
	{label: __("Group by ") + __("Invoice"), value: "Group by Invoice"},
	{label: __("Group by ") + __("Customer"), value: "Group by Customer"},
	{label: __("Group by ") + __("Customer Group"), value: "Group by Customer Group"},
	{label: __("Group by ") + __("Item"), value: "Group by Item"},
	{label: __("Group by ") + __("Item Group"), value: "Group by Item Group"},
	{label: __("Group by ") + __("Brand"), value: "Group by Brand"},
	{label: __("Group by ") + __("Warehouse"), value: "Group by Warehouse"},
	{label: __("Group by ") + __("Territory"), value: "Group by Territory"},
	{label: __("Group by ") + __("Sales Person"), value: "Group by Sales Person"},
	{label: __("Group by ") + __("Applies To Item"), value: "Group by Applies To Item"},
	{label: __("Group by ") + __("Applies To Variant Of"), value: "Group by Applies To Variant Of"},
	{label: __("Group by ") + __("Transaction Type"), value: "Group by Transaction Type"},
	{label: __("Group by ") + __("Project"), value: "Group by Project"},
	{label: __("Group by ") + __("Cost Center"), value: "Group by Cost Center"},
	{label: __("Group by ") + __("Branch"), value: "Group by Branch"},
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
			fieldname: "cost_center",
			label: __("Cost Center"),
			fieldtype: "Link",
			options: "Cost Center",
			get_query: () => {
				return { filters: { company: frappe.query_report.get_filter_value("company") } };
			},
		},
		{
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
		},
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project"
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
		{
			fieldname: "include_non_stock_items",
			label: __("Include Non Stock Items"),
			fieldtype: "Check",
		},
	],
	formatter: function(value, row, column, data, default_formatter) {
		let style = {};

		if ([
			'gross_profit', 'gross_profit_per_unit',
			'revenue', 'revenue_per_unit',
			'profit_margin', 'profit_markup',
			'cogs_qty', 'qty', 'stock_qty',
		].includes(column.fieldname)) {
			if (flt(value, 2) === 0) {
				style['color'] = 'var(--orange-500)';
			} else if (flt(value) < 0) {
				style['color'] = 'var(--red-600)';
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
