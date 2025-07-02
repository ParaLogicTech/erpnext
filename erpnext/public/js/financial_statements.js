frappe.provide("erpnext.financial_statements");

erpnext.financial_statements = {
	"filters": get_filters(),
	"formatter": function(value, row, column, data, default_formatter) {
		if (data && ((column.fieldname=="account") || (column.fieldname=="account_number") || (column.fieldname=="account_name"))) {

			if (!["account_name", "account_number"].includes(column.fieldname)) {
				value = data.account_name || value;
			}

			column.link_onclick =
				"erpnext.financial_statements.open_general_ledger(" + JSON.stringify(data) + ")";
			column.is_tree = true;
		}

		value = default_formatter(value, row, column, data);

		if (data && !data.parent_account) {
			value = $(`<span>${value}</span>`);

			var $value = $(value).css("font-weight", "bold");
			if (data.warn_if_negative && data[column.fieldname] < 0) {
				$value.addClass("text-danger");
			}

			value = $value.wrap("<p></p>").parent().html();
		}

		return value;
	},
	"open_general_ledger": function(data) {
		if (!data.account) return;
		var project = $.grep(frappe.query_report.filters, function(e){ return e.df.fieldname == 'project'; })

		frappe.route_options = {
			"account": data.account,
			"company": frappe.query_report.get_filter_value('company'),
			"from_date": data.from_date || data.year_start_date,
			"to_date": data.to_date || data.year_end_date,
			"project": (project && project.length > 0) ? project[0].$input.val() : ""
		};
		frappe.set_route("query-report", "General Ledger");
	},
	"tree": true,
	"name_field": "account",
	"parent_field": "parent_account",
	"initial_depth": 3,
	onload: function(report) {
		// dropdown for links to other financial statements
		erpnext.financial_statements.filters = get_filters()

		report.page.add_inner_button(__("Balance Sheet"), function() {
			var filters = report.get_values();
			frappe.set_route('query-report', 'Balance Sheet', {company: filters.company});
		}, __('Financial Statements'));
		report.page.add_inner_button(__("Profit and Loss"), function() {
			var filters = report.get_values();
			frappe.set_route('query-report', 'Profit and Loss Statement', {company: filters.company});
		}, __('Financial Statements'));
		report.page.add_inner_button(__("Cash Flow Statement"), function() {
			var filters = report.get_values();
			frappe.set_route('query-report', 'Cash Flow', {company: filters.company});
		}, __('Financial Statements'));
	},

	get_account_ledger_link: function(account, from_date, to_date) {
		const params = this.get_params_for_link();
		params["account"] = account;
		params["from_date"] = from_date;
		params["to_date"] = to_date;

		const query_string = Object.entries(params)
			.map(([key, val]) => `${key}=${encodeURIComponent(val)}`)
			.join('&');

		return `/app/query-report/General Ledger?${query_string}`;
	},

	get_summarized_statement_link: function(report_name, account_group, report_date) {
		let params = this.get_params_for_link();
		params["report_date"] = report_date;
		params["account_group"] = account_group;

		const query_string = Object.entries(params)
			.map(([key, val]) => `${key}=${encodeURIComponent(val)}`)
			.join('&');

		return `/app/query-report/${report_name}?${query_string}`;
	},

	get_params_for_link: function () {
		let params = {};

		let company = frappe.query_report.get_filter_value('company');
		if (company) {
			params["company"] = company;
		}

		let cost_center = frappe.query_report.get_filter_value('cost_center');
		if (cost_center) {
			params["cost_center"] = cost_center;
		}

		for (let dimension of erpnext.dimension_filters) {
			let dimension_field = dimension['fieldname'];
			let dimension_value = frappe.query_report.get_filter_value(dimension_field);

			if (dimension_value) {
				params[dimension_field] = dimension_value;
			}
		}

		return params;
	}
};

function get_filters() {
	let filters = [
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1
		},
		{
			"fieldname":"finance_book",
			"label": __("Finance Book"),
			"fieldtype": "Link",
			"options": "Finance Book"
		},
		{
			"fieldname":"from_fiscal_year",
			"label": __("Start Year"),
			"fieldtype": "Link",
			"options": "Fiscal Year",
			"default": frappe.defaults.get_user_default("fiscal_year"),
			"reqd": 1
		},
		{
			"fieldname":"to_fiscal_year",
			"label": __("End Year"),
			"fieldtype": "Link",
			"options": "Fiscal Year",
			"default": frappe.defaults.get_user_default("fiscal_year"),
			"reqd": 1
		},
		{
			"fieldname": "periodicity",
			"label": __("Periodicity"),
			"fieldtype": "Select",
			"options": [
				{ "value": "Monthly", "label": __("Monthly") },
				{ "value": "Quarterly", "label": __("Quarterly") },
				{ "value": "Half-Yearly", "label": __("Half-Yearly") },
				{ "value": "Yearly", "label": __("Yearly") }
			],
			"default": "Yearly",
			"reqd": 1
		},
		// Note:
		// If you are modifying this array such that the presentation_currency object
		// is no longer the last object, please make adjustments in cash_flow.js
		// accordingly.
		{
			"fieldname": "presentation_currency",
			"label": __("Currency"),
			"fieldtype": "Select",
			"options": erpnext.get_presentation_currency_list()
		},
		{
			"fieldname": "cost_center",
			"label": __("Cost Center"),
			"fieldtype": "MultiSelectList",
			get_data: function(txt) {
				return frappe.db.get_link_options('Cost Center', txt, {
					company: frappe.query_report.get_filter_value("company")
				});
			}
		}
	]

	return filters;
}


