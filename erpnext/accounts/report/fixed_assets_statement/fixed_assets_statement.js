frappe.query_reports["Fixed Assets Statement"] = {
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
			if (data.format_link) {
				let report_date = frappe.query_report.get_filter_value("report_date");

				if (column.account_group && report_date) {
					options.link_href = erpnext.financial_statements.get_summarized_statement_link(
						"Summarized Balance Sheet",
						column.account_group,
						report_date,
					);
				} else if (column.account && data.from_date && data.to_date) {
					options.link_href = erpnext.financial_statements.get_account_ledger_link(
						column.account,
						data.from_date,
						data.to_date,
					);
				}
			}

			if (data.is_bold) {
				options.css['font-weight'] = 'bold';
			}

			if (column.fieldname == "total" && data.fieldname == "nbv_opening") {
				options.css['font-weight'] = 'bold';
			}
		}

		return default_formatter(value, row, column, data, options);
	},
};

erpnext.utils.add_dimensions('Fixed Assets Statement', 5);
