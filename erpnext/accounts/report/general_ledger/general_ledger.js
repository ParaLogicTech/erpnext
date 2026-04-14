// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.query_reports["General Ledger"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			bold: 1,
			on_change: () => {
				let account = frappe.query_report.get_filter_value("account");
				let company = frappe.query_report.get_filter_value("company");
				if (!account || !company) {
					return;
				}

				frappe.call({
					method: "erpnext.accounts.doctype.journal_entry.journal_entry.get_other_company_account",
					args: {
						source_account: account,
						target_company: company,
					},
					callback: (r) => {
						if (r.message) {
							frappe.query_report.set_filter_value("account", r.message);
						}
					}
				})
			},
		},
		{
			fieldname: "account_filter",
			label: __("Account Filter By"),
			fieldtype: "Select",
			options: ["Account", "Multiple Accounts", "Account Group", "Account Type"],
			default: "Account",
			on_change: () => {
				frappe.query_reports["General Ledger"].set_account_type_options(frappe.query_report);
			}
		},
		{
			fieldname: "account",
			label: __("Account"),
			fieldtype: "Link",
			options: "Account",
			depends_on: "eval:doc.account_filter == 'Account' || !doc.account_filter",
			get_query: () => {
				return {
					filters: {
						company: frappe.query_report.get_filter_value('company'),
					}
				}
			}
		},
		{
			fieldname: "accounts",
			label: __("Accounts"),
			fieldtype: "MultiSelectList",
			options: "Account",
			depends_on: "eval:doc.account_filter == 'Multiple Accounts'",
			get_data: function (txt) {
				return frappe.db.get_link_options("Account", txt, {
					company: frappe.query_report.get_filter_value("company"),
				});
			},
		},
		{
			fieldname: "account_group",
			label: __("Account Group"),
			fieldtype: "Link",
			options: "Account Group",
			depends_on: "eval:doc.account_filter == 'Account Group'",
			get_query: () => {
				return {
					filters: {
						company: frappe.query_report.get_filter_value('company'),
					}
				}
			}
		},
		{
			fieldname: "account_type",
			label: __("Account Type"),
			fieldtype: "Select",
			options: [""],
			depends_on: "eval:doc.account_filter == 'Account Type'",
		},
		{
			fieldname: "party_type",
			label: __("Party Type"),
			fieldtype: "Link",
			options: "Party Type",
			default: "",
			on_change: function() {
				frappe.query_report.set_filter_value('party', "");
			}
		},
		{
			fieldname: "party",
			label: __("Party"),
			fieldtype: "Dynamic Link",
			options: "party_type",
			// get_data: function(txt) {
			// 	if (!frappe.query_report.filters) return;

			// 	let party_type = frappe.query_report.get_filter_value('party_type');
			// 	if (!party_type) return;

			// 	return frappe.db.get_link_options(party_type, txt);
			// },
			on_change: function() {
				var party_type = frappe.query_report.get_filter_value('party_type');
				var party = frappe.query_report.get_filter_value('party');
				var parties = party ? [party] : [];

				if(!party_type || parties.length === 0 || parties.length > 1) {
					frappe.query_report.set_filter_value('party_name', "");
					frappe.query_report.set_filter_value('tax_id', "");
				} else {
					party = parties[0];
					erpnext.utils.get_party_name(party_type, party, function (party_name) {
						frappe.query_report.set_filter_value('party_name', party_name);
					});

					if (party_type === "Customer" || party_type === "Supplier") {
						frappe.db.get_value(party_type, party, "tax_id", function(value) {
							frappe.query_report.set_filter_value('tax_id', value["tax_id"]);
						});
					}
				}
			}
		},
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: [
				"",
				"Group by Voucher",
				"Group by Account",
				"Group by Party",
				"Group by Account Manager",
				"Group by Sales Person",
			],
			default: ""
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "presentation_currency",
			label: __("Currency"),
			fieldtype: "Select",
			options: erpnext.get_presentation_currency_list()
		},
		{
			fieldname: "sales_person",
			label: __("Sales Person"),
			fieldtype: "Link",
			options: "Sales Person",
		},
		{
			fieldname: "account_manager",
			label: __("Account Manager"),
			fieldtype: "Link",
			options: "Sales Person",
		},
		{
			fieldname: "voucher_no",
			label: __("Voucher No"),
			fieldtype: "Data",
			on_change: function() {
				frappe.query_report.set_filter_value('group_by', "");
				frappe.query_report.set_filter_value('merge_similar_entries', 0);
			}
		},
		{
			fieldname: "voucher_filter_method",
			label: __("Voucher No Filter Method"),
			fieldtype: "Select",
			options: "Posted By Voucher\nPosted Against Voucher\nPosted By and Against Voucher",
			default: "Posted By Voucher",
		},
		{
			fieldname: "reference_no",
			label: __("Reference No"),
			fieldtype: "Data"
		},
		{
			fieldname: "finance_book",
			label: __("Finance Book"),
			fieldtype: "Link",
			options: "Finance Book"
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
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
		},
		{
			fieldtype: "Break",
		},
		{
			fieldname: "party_name",
			label: __("Party Name"),
			fieldtype: "Data",
			hidden: 1
		},
		{
			fieldname: "merge_similar_entries",
			label: __("Merge Similar Entries"),
			fieldtype: "Check",
			default: 0
		},
		{
			fieldname: "merge_dimensions",
			label: __("Merge Dimensions"),
			fieldtype: "Check",
			default: 0
		},
		{
			fieldname: "merge_linked_parties",
			label: __("Merge Linked Parties"),
			fieldtype: "Check"
		},
		{
			fieldname: "show_opening_entries",
			label: __("Show Opening Entries"),
			fieldtype: "Check"
		},
		{
			fieldname: "has_project",
			label: __("Project") + " " + __("Entries Only"),
			fieldtype: "Check",
		},
		{
			fieldname: "against_in_print",
			label: __("Against Column In Print"),
			fieldtype: "Check",
			on_change: function() { }
		},
		{
			fieldname: "show_items",
			label: __("Show Items in Print"),
			fieldtype: "Check",
		},
		{
			fieldname: "tax_id",
			label: __("Tax Id"),
			fieldtype: "Data",
			hidden: 1
		}
	],

	onload: function(report) {
        this.set_account_type_options(report);
    },

	set_account_type_options: function(report) {
		frappe.model.with_doctype("Account", function() {
            // Get account_type field options
            let df = frappe.get_meta("Account").fields.find(f => f.fieldname === "account_type");
			report.get_filter('account_type').df.options = df?.options ? df.options.split("\n") : [];
			report.get_filter('account_type').df.default = "";
			report.get_filter('account_type').refresh();
        });
	},
}

erpnext.utils.add_dimensions('General Ledger', 19);
erpnext.utils.add_additional_gl_filters('General Ledger');
