frappe.query_reports["Summarized Balance Sheet"] = {
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
					report_type: "Balance Sheet",
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
			let report_date = frappe.query_report.get_filter_value('report_date');
			let report_date_moment = moment(frappe.datetime.str_to_obj(report_date));

			let prev_year_date_moment = report_date_moment.subtract(1, "year");
			let prev_year_date = prev_year_date_moment.format();

			if (["actual_display", "prev_year_display"].includes(column.fieldname) && data.row_type === "Account Group") {
				options.link_href = erpnext.financial_statements.get_summarized_statement_link(
					"Summarized Balance Sheet",
					data.account_group,
					report_date,
				);
			}

			if (column.fieldname === "actual_display" && data.row_type === "Account") {
				let from_date = report_date_moment.startOf("year").format();
				options.link_href = erpnext.financial_statements.get_account_ledger_link(
					data.account,
					from_date,
					report_date
				);
			}

			if (column.fieldname === "prev_year_display" && data.row_type === "Account") {
				let from_date = prev_year_date_moment.startOf("year").format();
				options.link_href = erpnext.financial_statements.get_account_ledger_link(
					data.account,
					from_date,
					prev_year_date
				);
			}

			if (data.is_bold) {
				options.css['font-weight'] = 'bold';
			}
		}
		return default_formatter(value, row, column, data, options);
	},
};

erpnext.utils.add_dimensions('Summarized Balance Sheet', 5); 