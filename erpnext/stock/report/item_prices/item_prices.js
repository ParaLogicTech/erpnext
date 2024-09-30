// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Item Prices"] = {
	filters: [
		{
			fieldname: "date",
			label: __("Price Effective Date"),
			fieldtype: "Date",
			reqd: 1
		},
		{
			fieldname: "filter_price_list_by",
			label: __("Filter Price List By"),
			fieldtype: "Select",
			options:"Enabled\nDisabled\nAll",
			default:"Enabled"
		},
		{
			fieldname: "buying_selling",
			label: __("Buying Or Selling Prices"),
			fieldtype: "Select",
			options:"Selling\nBuying\nBoth",
			default:"Selling"
		},
		{
			fieldname: "selected_price_list",
			label: __("Selected Price List"),
			fieldtype: "Link",
			options:"Price List",
			get_query: () => frappe.query_reports["Item Prices"].price_list_query(),
		},
		{
			fieldname: "price_list_1",
			label: __("Comparison Price List"),
			fieldtype: "Link",
			options: "Price List",
			get_query: () => frappe.query_reports["Item Prices"].price_list_query(),
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options:"Item",
			get_query: function() {
				return {
					query: "erpnext.controllers.queries.item_query",
					filters: {'include_disabled': 1,'include_templates':1}
				}
			},
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options:"Item Group",
			default:""
		},
		{
			fieldname: "brand",
			label: __("Brand"),
			fieldtype: "Link",
			options:"Brand",
		},
		{
			fieldname: "customer",
			label: __("For Customer"),
			fieldtype: "Link",
			options:"Customer",
			on_change: function () {
				let customer = frappe.query_report.get_filter_value('customer');
				if(customer) {
					frappe.db.get_value("Customer", customer, "default_price_list", function(value) {
						frappe.query_report.set_filter_value('selected_price_list', value["default_price_list"]);
					});
				} else {
					frappe.query_report.set_filter_value('selected_price_list', '');
				}
			}
		},
		{
			fieldname: "supplier",
			label: __("For Supplier"),
			fieldtype: "Link",
			options:"Supplier",
			on_change: function () {
				let customer = frappe.query_report.get_filter_value('supplier');
				if(customer) {
					frappe.db.get_value("Supplier", customer, "default_price_list", function(value) {
						frappe.query_report.set_filter_value('selected_price_list', value["default_price_list"]);
					});
				} else {
					frappe.query_report.set_filter_value('selected_price_list', '');
				}
			}
		},
		{
			fieldname: "uom",
			label: __("UOM"),
			fieldtype: "Link",
			options:"UOM"
		},
		{
			fieldname: "default_uom",
			label: __("Default UOM"),
			fieldtype: "Select",
			options: "Default UOM\nStock UOM\nContents UOM",
			default: "Default UOM"
		},
		{
			fieldname: "customer_provided_items",
			label: __("Customer Provided Items"),
			fieldtype: "Select",
			options: [
				"",
				"Customer Provided Items Only",
				"Exclude Customer Provided Items",
			]
		},
		{
			fieldname: "filter_items_without_price",
			label: __("Filter Items Without Price"),
			fieldtype: "Check"
		},
		{
			fieldname: "show_valid_from",
			label: __("Show Valid From Date"),
			fieldtype: "Check"
		},
	],

	price_list_query: function () {
		let buying_selling = frappe.query_report.get_filter_value('buying_selling');
		if (buying_selling == "Selling") {
			return {
				filters: {selling: 1}
			}
		} else if (buying_selling == "Buying") {
			return {
				filters: {buying: 1}
			}
		}
	},

	formatter: function(value, row, column, data, default_formatter) {
		let original_value = value;

		let options = {
			link_target: "_blank",
			css: {},
		};

		if (column.price_list) {
			let old_rate_field = "rate_old_" + frappe.scrub(column.price_list);
			if (data.hasOwnProperty(old_rate_field)) {
				if (flt(original_value) < flt(data[old_rate_field])) {
					options.css['color'] = 'green';
				} else if (flt(original_value) > flt(data[old_rate_field])) {
					options.css['color'] = 'red';
				}
			}

			let item_price_field = "item_price_" + frappe.scrub(column.price_list);
			if (data.hasOwnProperty(item_price_field) && data[item_price_field]) {
				options.link_href = "/app/item-price/" + data[item_price_field];
			}
		}

		if (column.fieldname == "po_qty") {
			options.link_href = "/app/query-report/Purchase Items To Be Received?item_code=" + data.item_code;
		}

		if (['po_qty', 'actual_qty', 'standard_rate', 'avg_lc_rate'].includes(column.fieldname)) {
			options.css['font-weight'] = 'bold';
		}

		if (column.fieldname == "alt_uom_size") {
			options.always_show_decimals = 0;
		}

		return default_formatter(value, row, column, data, options);
	},

	onChange: function(new_value, column, data, rowIndex) {
		let method;
		let args;

		if (column.fieldname === "print_in_price_list") {
			method = "frappe.client.set_value";
			args = {
				doctype: "Item",
				name: data.item_code,
				fieldname: 'hide_in_price_list',
				value: cint(!new_value)
			};
		} else {
			method = "erpnext.stock.report.item_prices.item_prices.set_item_pl_rate";
			args = {
				effective_date: frappe.query_report.get_filter_value("date"),
				item_code: data['item_code'],
				price_list: column.price_list,
				price_list_rate: new_value,
				uom: data['uom'],
				filters: frappe.query_report.get_filter_values()
			};
		}

		return frappe.call({
			method: method,
			args: args,
			callback: function(r) {
				if (r.message) {
					frappe.query_report.datatable.datamanager.data[rowIndex] = r.message[1][0];

					frappe.query_report.datatable.datamanager.rowCount = 0;
					frappe.query_report.datatable.datamanager.columns = [];
					frappe.query_report.datatable.datamanager.rows = [];

					frappe.query_report.datatable.datamanager.prepareColumns();
					frappe.query_report.datatable.datamanager.prepareRows();
					frappe.query_report.datatable.datamanager.prepareTreeRows();
					frappe.query_report.datatable.datamanager.prepareRowView();
					frappe.query_report.datatable.datamanager.prepareNumericColumns();

					frappe.query_report.datatable.bodyRenderer.render();
				}
			}
		});
	}
};
