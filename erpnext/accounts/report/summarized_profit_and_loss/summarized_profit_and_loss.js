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
	],

	formatter: function(value, row, column, data, default_formatter) {
		let options = {
			css: {},
			link_target: "_blank",
		};

		if (data) {
			if (data.account_group && column.to_date && data.row_type === "Account Group") {
				options.link_href = erpnext.financial_statements.get_summarized_statement_link(
					"Summarized Profit and Loss",
					data.account_group,
					column.to_date,
				);
			}

			if (data.account && column.from_date && column.to_date && data.row_type === "Account") {
				options.link_href = erpnext.financial_statements.get_account_ledger_link(
					data.account,
					column.from_date,
					column.to_date,
				);
			}

			if (data.is_bold) {
				options.css['font-weight'] = 'bold';
			}
		}

		return default_formatter(value, row, column, data, options);
	},
};

erpnext.utils.add_dimensions('Summarized Profit and Loss', 5);