// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const spa_group_by_options = [
	"",
	{label: __("Group by ") + __("Supplier"), value: "Group by Supplier"},
	{label: __("Group by ") + __("Supplier Group"), value: "Group by Supplier Group"},
	{label: __("Group by ") + __("Cost Center"), value: "Group by Cost Center"},
	{label: __("Group by ") + __("Branch"), value: "Group by Branch"},
	{label: __("Group by ") + __("Project"), value: "Group by Project"},
]

frappe.query_reports["Supplier Payment Ageing"] = {
	"filters": [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company")
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.defaults.get_user_default("year_start_date"),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "ageing_based_on",
			label: __("Ageing Based On"),
			fieldtype: "Select",
			options: "Posting Date\nDue Date",
			default: "Posting Date",
		},
		{
			fieldname: "ageing_range",
			label: __("Ageing Range"),
			fieldtype: "Data",
			default: "30, 60, 90, 120",
		},
		{
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
			on_change: () => {
				let supplier = frappe.query_report.get_filter_value('supplier');
				if (supplier) {
					frappe.db.get_value('Supplier', supplier, ["supplier_name", "tax_id"], (value) => {
						frappe.query_report.set_filter_value('supplier_name', value["supplier_name"]);
						frappe.query_report.set_filter_value('tax_id', value["tax_id"]);
					});
				} else {
					frappe.query_report.set_filter_value('supplier_name', "");
					frappe.query_report.set_filter_value('tax_id', "");
				}
			},
			get_query: function() {
				return {
					query: "erpnext.controllers.queries.supplier_query"
				};
			}
		},
		{
			fieldname: "supplier_group",
			label: __("Supplier Group"),
			fieldtype: "Link",
			options: "Supplier Group",
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
			options: "Project",
		},
		{
			fieldname: "account",
			label: __("Payable Account"),
			fieldtype: "Link",
			options: "Account",
			get_query: function() {
				let company = frappe.query_report.get_filter_value('company');
				return {
					filters: {
						"company": company,
						"account_type": "Payable",
						"is_group": 0
					}
				}
			}
		},
		{
			fieldname: "group_by",
			label: __("Group By Level 1"),
			fieldtype: "Select",
			options: spa_group_by_options,
			default: ""
		},
		{
			fieldname: "group_by_2",
			label: __("Group By Level 2"),
			fieldtype: "Select",
			options: spa_group_by_options,
			default: ""
		},
		{
			fieldname: "exclude_unallocated",
			label: __("Exclude Unallocated Payment"),
			fieldtype: "Check",
		},
		{
			fieldname: "show_deduction_details",
			label: __("Show Deduction Details"),
			fieldtype: "Check",
		},
		{
			fieldname: "tax_id",
			label: __("Tax Id"),
			fieldtype: "Data",
			hidden: 1,
		},
		{
			fieldname: "supplier_name",
			label: __("Supplier Name"),
			fieldtype: "Data",
			hidden: 1,
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		let style = {};

		if (["opening_balance", "closing_balance"].includes(column.fieldname)) {
			style['font-weight'] = 'bold';
		}

		if (flt(value) && (column.fieldname == "total_deductions" || column.is_adjustment)) {
			style['color'] = 'var(--purple-600)';
		}

		if (flt(value) && column.fieldname == "payment_amount") {
			style['color'] = 'var(--blue-700)';
		}

		if (flt(value) && column.fieldname == "cleared_amount") {
			style['color'] = 'var(--blue-700)';
		}

		if (
			column.fieldname == "due_date"
			&& data?.payment_date
			&& data?.due_date
		) {
			let payment_date = frappe.datetime.str_to_obj(data.payment_date);
			let due_date = frappe.datetime.str_to_obj(data.due_date);
			if (payment_date > due_date) {
				style['color'] = 'var(--red-600)';
			} else if (payment_date < due_date) {
				style['color'] = 'var(--green-800)';
			} else {
				style['color'] = 'var(--blue-700)';
			}
		}

		return default_formatter(value, row, column, data, {css: style});
	},

	initial_depth: 1,
};
