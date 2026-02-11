// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

const ap_group_by_options = [
	"",
	{label: __("Group by ") + __("Supplier"), value: "Group by Supplier"},
	{label: __("Group by ") + __("Supplier Group"), value: "Group by Supplier Group"},
	{label: __("Group by ") + __("Cost Center"), value: "Group by Cost Center"},
	{label: __("Group by ") + __("Branch"), value: "Group by Branch"},
	{label: __("Group by ") + __("Project"), value: "Group by Project"},
]

frappe.query_reports["Accounts Payable"] = {
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
			"fieldname":"ageing_based_on",
			"label": __("Ageing Based On"),
			"fieldtype": "Select",
			"options": 'Posting Date\nDue Date\nSupplier Invoice Date',
			"default": "Posting Date"
		},
		{
			"fieldname":"report_date",
			"label": __("As on Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today()
		},
		{
			"fieldname":"ageing_range",
			"label": __("Ageing Range"),
			"fieldtype": "Data",
			"default": "30, 60, 90, 120",
			"reqd": 0
		},
		{
			"fieldname":"supplier",
			"label": __("Supplier"),
			"fieldtype": "Link",
			"options": "Supplier",
			on_change: () => {
				var supplier = frappe.query_report.get_filter_value('supplier');
				if (supplier) {
					frappe.db.get_value('Supplier', supplier, "tax_id", function(value) {
						frappe.query_report.set_filter_value('tax_id', value["tax_id"]);
					});
				} else {
					frappe.query_report.set_filter_value('tax_id', "");
				}
			}
		},
		{
			"fieldname":"supplier_group",
			"label": __("Supplier Group"),
			"fieldtype": "Link",
			"options": "Supplier Group"
		},
		{
			"fieldname": "account",
			"label": __("Payable Account"),
			"fieldtype": "Link",
			"options": "Account",
			"get_query": function() {
				var company = frappe.query_report.get_filter_value('company');
				return {
					"doctype": "Account",
					"filters": {
						"company": company,
						"account_type": "Payable",
						"is_group": 0
					}
				}
			}
		},
		{
			"fieldname":"payment_terms_template",
			"label": __("Payment Terms Template"),
			"fieldtype": "Link",
			"options": "Payment Terms Template"
		},
		{
			"fieldname": "cost_center",
			"label": __("Cost Center"),
			"fieldtype": "Link",
			"options": "Cost Center",
			get_query: () => {
				return { filters: { company: frappe.query_report.get_filter_value("company") } };
			},
		},
		{
			"fieldname": "branch",
			"label": __("Branch"),
			"fieldtype": "Link",
			"options": "Branch",
		},
		{
			"fieldname": "project",
			"label": __("Project"),
			"fieldtype": "Link",
			"options": "Project",
		},
		{
			"fieldname":"group_by",
			"label": __("Group By Level 1"),
			"fieldtype": "Select",
			"options": ap_group_by_options,
			"default": ""
		},
		{
			"fieldname":"group_by_2",
			"label": __("Group By Level 2"),
			"fieldtype": "Select",
			"options": ap_group_by_options,
			"default": ""
		},
		{
			"fieldname":"has_item",
			"label": __("Has Item"),
			"fieldtype": "Link",
			"options": "Item",
			"get_query": function() {
				return {
					query: "erpnext.controllers.queries.item_query",
					filters: {'include_disabled': 1}
				};
			}
		},
		{
			"fieldname":"based_on_payment_terms",
			"label": __("Based On Payment Terms"),
			"fieldtype": "Check",
		},
		{
			"fieldname":"mark_overdue_in_print",
			"label": __("Mark Overdue in Print"),
			"fieldtype": "Check",
			on_change: function() { return false; }
		},
		{
			"fieldname":"tax_id",
			"label": __("Tax Id"),
			"fieldtype": "Data",
			"hidden": 1
		}
	],
	onload: function(report) {
		report.page.add_inner_button(__("Accounts Payable Summary"), function() {
			var filters = report.get_values();
			frappe.set_route('query-report', 'Accounts Payable Summary', {company: filters.company});
		});
		erpnext.utils.add_payment_reconciliation_button("Supplier", report.page, () => report.get_values());
	},
	get_datatable_options(options) {
		return Object.assign(options, {
			hooks: {
				columnTotal: function (values, column, type) {
					if (in_list(['cumulative_outstanding'], column.column.fieldname)) {
						return '';
					} else {
						return frappe.utils.report_column_total(values, column, type);
					}
				}
			},
		});
	},
	initial_depth: 1
}

//erpnext.utils.add_dimensions('Accounts Payable', 9);

