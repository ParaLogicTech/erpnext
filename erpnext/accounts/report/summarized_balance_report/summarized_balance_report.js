frappe.query_reports["Summarized Balance Report"] = {
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
			if (["account_name", "actual_display", "prev_year_display"].includes(column.fieldname) && data.row_type === "Account Group") {
				options.link_href = this.get_account_group_link(data);
			}
			if (["actual_display", "prev_year_display"].includes(column.fieldname) && data.row_type === "Account") {
				let report_date = frappe.datetime.str_to_obj(frappe.query_report.get_filter_value('report_date'));
				let from_date = moment(report_date).startOf("year").format();
				options.link_href = this.get_account_link(data, from_date);
				options.link_target = "_blank";
			}
			if (data.is_bold) {
				options.css['font-weight'] = 'bold';
			}
		}
		return default_formatter(value, row, column, data, options);
	},

	get_account_link: function(data, from_date) {
		const params = {
			account: data.account,
			company: frappe.query_report.get_filter_value('company'),
			from_date: from_date,
			to_date: frappe.query_report.get_filter_value('report_date')
		};
		const query_string = Object.entries(params)
			.map(([key, val]) => `${key}=${encodeURIComponent(val)}`)
			.join('&');
		return `/app/query-report/General Ledger?${query_string}`;
	},

	get_account_group_link: function(data) {
		const params = {
			company: frappe.query_report.get_filter_value('company'),
			report_date: frappe.query_report.get_filter_value('report_date'),
			account_group: data.account_name,
		};
		const query_string = Object.entries(params)
			.map(([key, val]) => `${key}=${encodeURIComponent(val)}`)
			.join('&');
		return `/app/query-report/Summarized Balance Report?${query_string}`;
	},
};

erpnext.utils.add_dimensions('Summarized Balance Report', 5); 