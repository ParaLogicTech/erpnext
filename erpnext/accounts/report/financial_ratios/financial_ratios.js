frappe.query_reports["Financial Ratios"] = {
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
			fieldname: "account_group",
			label: __("Account Group"),
			fieldtype: "Link",
			options: "Account Group",
			get_query: () => ({
				filters: {
					company: frappe.query_report.get_filter_value('company'),
					report_type: "Ratios",
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
			fieldname: "show_hidden",
			label: __("Show Hidden Working"),
			fieldtype: "Check",
		},
	],

	formatter: function(value, row, column, data, default_formatter) {
		return erpnext.financial_statements.summarized_statement_formatter(value, row, column, data, default_formatter);
	},

	initial_depth: 0,
};

erpnext.utils.add_dimensions('Financial Ratios', 4);
