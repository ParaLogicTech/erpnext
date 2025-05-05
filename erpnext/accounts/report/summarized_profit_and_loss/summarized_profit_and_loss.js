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
					reporting_type: "Profit and Loss",
				}
			})
		},
	],

	formatter: function(value, row, column, data, default_formatter) {
		let options = {
			css: {},
			link_target: "_blank",
		};

		// Handle account name column formatting
		if (data) {
			if (["account_name", "mtd_actual", "ytd_actual"].includes(column.fieldname) && data.row_type === "Account Group") {
				options.link_href = this.get_account_group_link(data);
				// let account_group = data.account_name;
				// options.link_onclick = `
				// 	let account_group = '${account_group.replace("'", "\"")}'
				// 	frappe.query_report.set_filter_value('account_group', account_group);
				// 	event.preventDefault();
				// `;
			}
			if (column.fieldname === "mtd_actual" && data.row_type === "Account") {
				let report_date = frappe.datetime.str_to_obj(frappe.query_report.get_filter_value('report_date'));
				let from_date = moment(report_date).startOf("month").format();
				options.link_href = this.get_account_link(data, from_date);
				options.link_target = "_blank";
			}
			if (column.fieldname === "ytd_actual" && data.row_type === "Account") {
				let report_date = frappe.datetime.str_to_obj(frappe.query_report.get_filter_value('report_date'));
				let from_date = moment(report_date).startOf("year").format();
				options.link_href = this.get_account_link(data, from_date);
				options.link_target = "_blank";
			}

			// Make text bold if specified
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

		return `/app/query-report/Summarized Profit and Loss?${query_string}`;
	},
};
