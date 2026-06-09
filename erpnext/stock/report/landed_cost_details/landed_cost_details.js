const lc_details_group_by_options = [
	"",
	{label: __("Group by ") + __("Supplier"), value: "Group by Supplier"},
	{label: __("Group by ") + __("Supplier Group"), value: "Group by Supplier Group"},
	{label: __("Group by ") + __("Transaction"), value: "Group by Transaction"},
	{label: __("Group by ") + __("Branch"), value: "Group by Branch"},
	{label: __("Group by ") + __("Item"), value: "Group by Item"},
	{label: __("Group by ") + __("Item Group"), value: "Group by Item Group"},
	{label: __("Group by ") + __("Brand"), value: "Group by Brand"},
]

frappe.query_reports["Landed Cost Details"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			bold: 1
		},
		{
			fieldname: "qty_field",
			label: __("Quantity Type"),
			fieldtype: "Select",
			options: ["Stock Qty", "Contents Qty", "Transaction Qty"],
			default: "Stock Qty",
			reqd: 1
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1
		},
		{
			fieldname: "name",
			label: __("Purchase Invoice"),
			fieldtype: "Link",
			options: "Purchase Invoice",
			get_query: () => {
				return {
					filters: {
						docstatus: 1,
					}
				}
			}
		},
		{
			fieldname: "letter_of_credit",
			label: __("Letter of Credit"),
			fieldtype: "Link",
			options: "Letter of Credit"
		},
		{
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier"
		},
		{
			fieldname: "supplier_group",
			label: __("Supplier Group"),
			fieldtype: "Link",
			options: "Supplier Group"
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
			get_query: function() {
				return {
					query: "erpnext.controllers.queries.item_query",
					filters: {'include_disabled': 1}
				}
			},
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group"
		},
		{
			fieldname: "brand",
			label: __("Brand"),
			fieldtype: "Link",
			options: "Brand"
		},
		{
			fieldname: "transaction_type",
			label: __("Transaction Type"),
			fieldtype: "Link",
			options: "Transaction Type"
		},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: function() {
				return {
					filters: {'company': frappe.query_report.get_filter_value("company")}
				}
			},
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
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
		},
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
		},
		{
			fieldname: "group_by_1",
			label: __("Group By Level 1"),
			fieldtype: "Select",
			options: lc_details_group_by_options,
			default: ""
		},
		{
			fieldname: "group_by_2",
			label: __("Group By Level 2"),
			fieldtype: "Select",
			options: lc_details_group_by_options,
			default: ""
		},
		{
			fieldname: "group_by_3",
			label: __("Group By Level 3"),
			fieldtype: "Select",
			options: lc_details_group_by_options,
			default: ""
		},
		{
			fieldname: "group_same_items",
			label: __("Group Same Items"),
			fieldtype: "Check",
			default: 1
		},
		{
			fieldname: "totals_only",
			label: __("Group Totals Only"),
			fieldtype: "Check",
		},
	],

	formatter: function(value, row, column, data, default_formatter) {
		let style = {};

		if (['qty', 'net_amount', 'base_net_amount', 'taxes_in_valuation', 'taxes_not_in_valuation'].includes(column.fieldname)) {
			if (flt(value) < 0) {
				style['color'] = 'red';
			}
		}

		if (['debit_note_amount'].includes(column.fieldname)) {
			if (flt(value)) {
				style['color'] = 'var(--green-800)';
			}
		}

		if (['taxes_not_in_valuation'].includes(column.fieldname)) {
			if (flt(value)) {
				style['color'] = 'var(--blue-800)';
			}
		}

		if (['taxes_in_valuation'].includes(column.fieldname)) {
			if (flt(value)) {
				style['color'] = 'var(--orange-800)';
			}
		}

		if (['total_landed_cost', 'landed_cost_rate'].includes(column.fieldname)) {
			style['font-weight'] = 'bold';
		}

		return default_formatter(value, row, column, data, {css: style});
	},

	initial_depth: 1
}
