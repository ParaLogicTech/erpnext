frappe.provide("erpnext.financial_statements");

erpnext.financial_statements = {
	"filters": get_filters(),
	"formatter": function(value, row, column, data, default_formatter) {
		let options = {
			css: {},
			link_target: "_blank",
		}

		if (data && data.account && (["account", "account_number", "account_name", "account_display"].includes(column.fieldname))) {
			options.link_href = erpnext.financial_statements.get_account_ledger_link(
				data.account,
				data.from_date || data.year_start_date || frappe.query_report.get_filter_value("from_date"),
				data.to_date || data.year_end_date || frappe.query_report.get_filter_value("to_date"),
			);
			column.is_tree = true;
		}

		if (data && !data.parent_account) {
			options.css["font-weight"] = "bold";
			if (data.warn_if_negative && flt(data[column.fieldname], 3) < 0) {
				options.css["color"] = "var(--red-500)";
			}
		}

		value = default_formatter(value, row, column, data, options);

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

	summarized_statement_formatter: function(value, row, column, data, default_formatter) {
		let options = {
			css: {},
			link_target: "_blank",
		};

		if (data) {
			if (column.fieldname == "account_display") {
				if (data.row_type == "Account Group" && data.account_group) {
					options.link_href = frappe.utils.get_form_link("Account Group", data.account_group);
				} else if (data.row_type == "Account" && data.account) {
					options.link_href = frappe.utils.get_form_link("Account", data.account);
				}
			}

			if (column.format_link) {
				let report_date = frappe.query_report.get_filter_value("report_date");

				if (data.account_group && report_date && data.row_type === "Account Group") {
					let report_name = frappe.query_report.report_name;
					if (data.is_fixed_asset_root) {
						report_name = "Fixed Assets Statement";
					}
					options.link_href = erpnext.financial_statements.get_summarized_statement_link(
						report_name,
						data.account_group,
						report_date,
					);
				} else if (data.account && column.from_date && column.to_date && data.row_type === "Account") {
					options.link_href = erpnext.financial_statements.get_account_ledger_link(
						data.account,
						column.from_date,
						column.to_date,
					);
				}
			}

			if (data.is_bold) {
				options.css['font-weight'] = 'bold';
			}

			if (column.is_value_field) {
				column = Object.assign({}, column);
				column.fieldtype = data.value_type || "Currency";
				column.precision = data.format_precision;
				column.options = column.fieldtype == "Currency" ? "currency" : null;
			}
		}
		return default_formatter(value, row, column, data, options);
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


