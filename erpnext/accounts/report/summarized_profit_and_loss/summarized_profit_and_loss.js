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
            value = this.format_account_name(value, data);
        }

        // Make text bold if specified
        if (data.is_bold) {
            value = value.bold();
        }

        return value;
    },

    format_account_name: function(value, data) {
        if (data.row_type === "Account") {
            return this.create_account_link(value, data);
        } else if (data.row_type === "Account Group") {
            return this.create_account_group_link(value, data);
        }
        return value;
    },

    create_account_link: function(value, data) {
        const params = {
            account: data.account,
            company: frappe.query_report.get_filter_value('company'),
            from_date: frappe.datetime.month_start(frappe.query_report.get_filter_value('report_date')),
            to_date: frappe.query_report.get_filter_value('report_date')
        };

        const query_string = Object.entries(params)
            .map(([key, val]) => `${key}=${encodeURIComponent(val)}`)
            .join('&');

        const report_url = frappe.urllib.get_full_url(`/app/query-report/General Ledger?${query_string}`);
        return `<a href="${report_url}" data-account="${data.account}">${value}</a>`;
    },

    create_account_group_link: function(value, data) {
        const current_url = frappe.urllib.get_full_url(window.location.pathname);
        const group_url = `${current_url}?account_group=${encodeURIComponent(data.account_group)}`;
        return `<a href="${group_url}" data-account-group="${data.account_group}">${value}</a>`;
    },

    handle_account_click: function(e) {
        if (e.which !== 1) return; // Only handle left clicks

        e.preventDefault();
        const account = $(e.currentTarget).attr('data-account');
        const params = {
            account: account,
            company: frappe.query_report.get_filter_value('company'),
            from_date: frappe.datetime.month_start(frappe.query_report.get_filter_value('report_date')),
            to_date: frappe.query_report.get_filter_value('report_date')
        };
        const query_string = Object.entries(params)
            .map(([key, val]) => `${key}=${encodeURIComponent(val)}`)
            .join('&');
        const report_url = frappe.urllib.get_full_url(`/app/query-report/General Ledger?${query_string}`);
        window.location.href = report_url;
    },

    handle_account_group_click: function(e) {
        if (e.which !== 1) return; // Only handle left clicks

        e.preventDefault();
        const account_group = $(e.currentTarget).attr('data-account-group');
        frappe.query_report.set_filter_value('account_group', account_group);
        frappe.query_report.refresh();
    },

    onload: function(report) {
        // Attach click handlers
        report.page.wrapper
            .on('click', 'a[data-account]', this.handle_account_click)
            .on('click', 'a[data-account-group]', this.handle_account_group_click);
    },

    tree: true,
    parent_field: "parent_account",
    name_field: "account",
    initial_depth: 1
}; 