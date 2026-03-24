frappe.query_reports["Summarized Profit and Loss"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1
		},
		{
			fieldname: "report_date",
			label: __("Report Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 1
		},
		{
			fieldname: "format",
			label: __("Format"),
			fieldtype: "Select",
			options: [
				"MTD/YTD",
				"Monthly",
				"Dimension MTD",
				"Dimension YTD",
			],
			default: "MTD/YTD",
		},
		{
			fieldname: "dimension_field",
			label: __("Group by Dimension"),
			fieldtype: "Select",
			options: [
				{label: __("Cost Center"), value: "cost_center"},
			].concat(erpnext.financial_statements.get_dimension_options()),
			depends_on: "eval:['Dimension MTD', 'Dimension YTD'].includes(doc.format)",
		},
		{
			fieldname: "account_group",
			label: __("Account Group"),
			fieldtype: "Link",
			options: "Account Group",
			get_query: () => ({
				filters: {
					company: frappe.query_report.get_filter_value('company'),
					report_type: "Profit and Loss",
				}
			})
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
			fieldname: "tree_view",
			label: __("Tree View"),
			fieldtype: "Check",
		},
		{
			fieldname: "hide_budget",
			label: __("Hide Budget"),
			fieldtype: "Check",
		},
		{
			fieldname: "has_project",
			label: __("Project") + " " + __("Entries Only"),
			fieldtype: "Check",
		},
	],

	formatter: function(value, row, column, data, default_formatter) {
		return erpnext.financial_statements.summarized_statement_formatter(value, row, column, data, default_formatter);
	},

	initial_depth: 0,
};

erpnext.utils.add_dimensions('Summarized Profit and Loss', 5);