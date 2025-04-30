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
            fieldname: "account_group",
            label: __("Account Group"),
            fieldtype: "Link",
            options: "Account Group",
            get_query: () => ({
                filters: {
                    company: frappe.query_report.get_filter_value('company'),
                    reporting_type: "Profit and Loss"
                }
            })
        },
        {
            fieldname: "report_date",
            label: __("Report Date"),
            fieldtype: "Date",
            default: frappe.datetime.month_end(frappe.datetime.get_today()),
            reqd: 1
        }
    ],

    formatter: function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        
        if (!data) return value;

        // Handle account name column formatting
        if (column.fieldname === "account_name") {
            value = this.formatAccountName(value, data);
        }

        // Make text bold if specified
        if (data.is_bold) {
            value = value.bold();
        }

        return value;
    },

    formatAccountName: function(value, data) {
        if (data.row_type === "Account") {
            return this.createAccountLink(value, data);
        } else if (data.row_type === "Account Group") {
            return this.createAccountGroupLink(value, data);
        }
        return value;
    },

    createAccountLink: function(value, data) {
        const params = {
            account: data.account,
            company: frappe.query_report.get_filter_value('company'),
            from_date: frappe.datetime.month_start(frappe.query_report.get_filter_value('report_date')),
            to_date: frappe.query_report.get_filter_value('report_date')
        };

        const queryString = Object.entries(params)
            .map(([key, val]) => `${key}=${encodeURIComponent(val)}`)
            .join('&');

        const reportUrl = frappe.urllib.get_full_url(`/app/query-report/General Ledger?${queryString}`);
        return `<a href="${reportUrl}" data-account="${data.account}">${value}</a>`;
    },

    createAccountGroupLink: function(value, data) {
        const currentUrl = frappe.urllib.get_full_url(window.location.pathname);
        const groupUrl = `${currentUrl}?account_group=${encodeURIComponent(data.account_group)}`;
        return `<a href="${groupUrl}" data-account-group="${data.account_group}">${value}</a>`;
    },

    isCurrencyField: function(fieldname) {
        const currencyFields = [
            "mtd_actual", "mtd_budget", "mtd_prev_year",
            "ytd_actual", "ytd_budget", "ytd_prev_year"
        ];
        return currencyFields.includes(fieldname);
    },


    handleAccountClick: function(e) {
        if (e.which !== 1) return; // Only handle left clicks

        e.preventDefault();
        const account = $(e.currentTarget).attr('data-account');
        
        frappe.route_options = {
            account: account,
            company: frappe.query_report.get_filter_value('company'),
            from_date: frappe.datetime.month_start(frappe.query_report.get_filter_value('report_date')),
            to_date: frappe.query_report.get_filter_value('report_date')
        };
        
        frappe.set_route("query-report", "General Ledger");
    },

    handleAccountGroupClick: function(e) {
        if (e.which !== 1) return; // Only handle left clicks

        e.preventDefault();
        const accountGroup = $(e.currentTarget).attr('data-account-group');
        frappe.query_report.set_filter_value('account_group', accountGroup);
        frappe.query_report.refresh();
    },

    onload: function(report) {
        // Attach click handlers
        report.page.wrapper
            .on('click', 'a[data-account]', this.handleAccountClick)
            .on('click', 'a[data-account-group]', this.handleAccountGroupClick);
    },

    tree: true,
    parent_field: "parent_account",
    name_field: "account",
    initial_depth: 1
}; 