// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext.item");

frappe.ui.form.on("Item", {
	setup: function(frm) {
		frm.add_fetch('attribute', 'numeric_values', 'numeric_values');
		frm.add_fetch('attribute', 'from_range', 'from_range');
		frm.add_fetch('attribute', 'to_range', 'to_range');
		frm.add_fetch('attribute', 'increment', 'increment');
		frm.add_fetch('tax_type', 'tax_rate', 'tax_rate');
	},
	onload: function(frm) {
		erpnext.item.setup_queries(frm);
		if (frm.doc.variant_of){
			frm.fields_dict["attributes"].grid.set_column_disp("attribute_value", true);
		}

		if (frm.doc.is_fixed_asset) {
			frm.trigger("set_asset_naming_series");
		}
	},

	refresh: function(frm) {
		if (frm.doc.is_stock_item) {
			frm.add_custom_button(__("Balance"), function() {
				frappe.route_options = {
					"item_code": frm.doc.name
				}
				frappe.set_route("query-report", "Stock Balance");
			}, __("View"));
			frm.add_custom_button(__("Ledger"), function() {
				frappe.route_options = {
					"item_code": frm.doc.name,
					"from_date": frappe.defaults.get_user_default("year_start_date"),
					"to_date": frappe.defaults.get_user_default("year_end_date")
				}
				frappe.set_route("query-report", "Stock Ledger");
			}, __("View"));
			frm.add_custom_button(__("Projected"), function() {
				frappe.route_options = {
					"item_code": frm.doc.name
				}
				frappe.set_route("query-report", "Stock Projected Qty");
			}, __("View"));
		}

		const cant_change_fields = (frm.doc.__onload && frm.doc.__onload.cant_change_fields) || [];
		if(frm.has_perm("write") && (cant_change_fields.includes('stock_uom') || cant_change_fields.includes('alt_uom'))) {
			frm.add_custom_button(__("Unit of Measure"), function () {
				erpnext.item.change_uom(frm);
			}, __("Change"))
		}

		if (!frm.doc.is_fixed_asset) {
			erpnext.item.make_dashboard(frm);
		}

		if (frm.doc.is_fixed_asset) {
			frm.trigger('is_fixed_asset');
			frm.trigger('auto_create_assets');
		}

		// clear intro
		frm.set_intro();

		if (frm.doc.has_variants) {
			frm.set_intro(__("This Item is a Template and cannot be used in transactions. Item attributes will be copied over into the variants unless 'No Copy' is set"), true);
			frm.add_custom_button(__("Show Variants"), function() {
				frappe.set_route("List", "Item", {"variant_of": frm.doc.name});
			}, __("View"));

			frm.add_custom_button(__("Variant Details Report"), function() {
				frappe.set_route("query-report", "Item Variant Details", {"item": frm.doc.name});
			}, __("View"));

			if(frm.doc.variant_based_on==="Item Attribute") {
				frm.add_custom_button(__("Single Variant"), function() {
					erpnext.item.show_single_variant_dialog(frm);
				}, __('Create'));
				frm.add_custom_button(__("Multiple Variants"), function() {
					erpnext.item.show_multiple_variants_dialog(frm);
				}, __('Create'));
			} else {
				frm.add_custom_button(__("Variant"), function() {
					erpnext.item.show_modal_for_manufacturers(frm);
				}, __('Create'));
			}

			frm.page.set_inner_btn_group_as_primary(__('Create'));
		}
		if (frm.doc.variant_of) {
			frm.set_intro(__('This Item is a Variant of {0} (Template).',
				[`<a href="/app/item/${encodeURIComponent(frm.doc.variant_of)}">${frm.doc.variant_of}</a>`]), true);
		}

		erpnext.item.edit_prices_button(frm);
		erpnext.item.toggle_attributes(frm);

		frm.add_custom_button(__('Duplicate'), function() {
			var new_item = frappe.model.copy_doc(frm.doc);
			if(new_item.item_name===new_item.item_code) {
				new_item.item_name = null;
			}
			if(new_item.description===new_item.description) {
				new_item.description = null;
			}
			frappe.set_route('Form', 'Item', new_item.name);
		});

		if(frm.doc.has_variants) {
			frm.add_custom_button(__("Item Variant Settings"), function() {
				frappe.set_route("Form", "Item Variant Settings");
			}, __("View"));
		}

		const alt_uom_readonly = (!frm.doc.__islocal && frm.doc.alt_uom && flt(frm.doc.alt_uom_size)) ? 1 : 0;
		frm.set_df_property('alt_uom_size', 'read_only', alt_uom_readonly);

		cant_change_fields.forEach((fieldname) => {
			frm.set_df_property(fieldname, "read_only_depends_on", null);
			frm.set_df_property(fieldname, "read_only", 1);
		});
	},

	validate: function(frm){
		erpnext.item.weight_to_validate(frm);
	},

	image: function() {
		refresh_field("image_view");
	},

	is_customer_provided_item: function(frm) {
		frm.set_value("is_purchase_item", frm.doc.is_customer_provided_item ? 0 : 1);
		frm.events.set_customer_provided_material_request_type(frm);
	},

	is_sub_contracted_item: function (frm) {
		frm.events.set_customer_provided_material_request_type(frm);
	},

	set_customer_provided_material_request_type: function (frm) {
		if (frm.doc.is_customer_provided_item) {
			frm.set_value("default_material_request_type", frm.doc.is_sub_contracted_item ? "Purchase" : "Customer Provided");
		}
	},

	is_fixed_asset: function(frm) {
		// set serial no to false & toggles its visibility
		frm.set_value('has_serial_no', 0);
		frm.toggle_enable(['has_serial_no', 'serial_no_series'], !frm.doc.is_fixed_asset);
		frm.toggle_reqd(['asset_category'], frm.doc.is_fixed_asset);
		frm.toggle_display(['has_serial_no', 'serial_no_series'], !frm.doc.is_fixed_asset);

		frm.call({
			method: "set_asset_naming_series",
			doc: frm.doc,
			callback: function() {
				frm.set_value("is_stock_item", frm.doc.is_fixed_asset ? 0 : 1);
				frm.trigger("set_asset_naming_series");
			}
		});

		frm.trigger('auto_create_assets');
	},

	set_asset_naming_series: function(frm) {
		if (frm.doc.__onload && frm.doc.__onload.asset_naming_series) {
			frm.set_df_property("asset_naming_series", "options", frm.doc.__onload.asset_naming_series);
		}
	},

	auto_create_assets: function(frm) {
		frm.toggle_reqd(['asset_naming_series'], frm.doc.auto_create_assets);
		frm.toggle_display(['asset_naming_series'], frm.doc.auto_create_assets);
	},

	brand: function(frm) {
		erpnext.utils.set_item_overrides(frm);
	},
	item_group: function(frm) {
		erpnext.utils.set_item_overrides(frm);
	},
	item_source: function(frm) {
		erpnext.utils.set_item_overrides(frm);
	},

	item_code: function(frm) {
		// if(!frm.doc.item_name)
		// 	frm.set_value("item_name", frm.doc.item_code);
		// if(!frm.doc.description)
		// 	frm.set_value("description", frm.doc.item_code);
	},

	is_stock_item: function(frm) {
		if(!frm.doc.is_stock_item) {
			frm.set_value("has_batch_no", 0);
			frm.set_value("create_new_batch", 0);
			frm.set_value("has_serial_no", 0);
		}
	},

	has_variants: function(frm) {
		erpnext.item.toggle_attributes(frm);
	},

	net_weight_per_unit: function (frm) {
		frm.events.calculate_gross_weight(frm);
	},
	tare_weight_per_unit: function (frm) {
		frm.events.calculate_gross_weight(frm);
	},
	gross_weight_per_unit: function (frm) {
		if (flt(frm.doc.net_weight_per_unit)) {
			let new_tare_weight = flt(flt(frm.doc.gross_weight_per_unit) - flt(frm.doc.net_weight_per_unit),
				precision("tare_weight_per_unit"));
			frm.set_value("tare_weight_per_unit", new_tare_weight);
		}
	},

	calculate_gross_weight: function (frm) {
		let weight_fields = ["net_weight_per_unit", "tare_weight_per_unit", "gross_weight_per_unit"];
		frappe.model.round_floats_in(frm.doc, weight_fields);

		if (!frm.doc.is_packaging_material) {
			if (flt(frm.doc.net_weight_per_unit)) {
				frm.doc.gross_weight_per_unit = flt(flt(frm.doc.net_weight_per_unit) + flt(frm.doc.tare_weight_per_unit),
					precision("gross_weight_per_unit"));

				frm.refresh_field("gross_weight_per_unit");
			} else if (flt(frm.doc.gross_weight_per_unit) && flt(frm.doc.tare_weight_per_unit)) {
				frm.doc.net_weight_per_unit = flt(flt(frm.doc.gross_weight_per_unit) - flt(frm.doc.tare_weight_per_unit),
					precision("gross_weight_per_unit"));

				frm.refresh_field("net_weight_per_unit");
			}
		}
	}
});

frappe.ui.form.on('Item Reorder', {
	reorder_levels_add: function(frm, cdt, cdn) {
		var row = frappe.get_doc(cdt, cdn);
		var type = frm.doc.default_material_request_type
		row.material_request_type = (type == 'Material Transfer')? 'Transfer' : type;
	}
})

frappe.ui.form.on('Item Customer Detail', {
	customer_items_add: function(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, 'customer_group', "");
	},
	customer_name: function(frm, cdt, cdn) {
		set_customer_group(frm, cdt, cdn);
	},
	customer_group: function(frm, cdt, cdn) {
		if(set_customer_group(frm, cdt, cdn)){
			frappe.msgprint(__("Changing Customer Group for the selected Customer is not allowed."));
		}
	}
});

var set_customer_group = function(frm, cdt, cdn) {
	var row = frappe.get_doc(cdt, cdn);

	if (!row.customer_name) {
		return false;
	}

	frappe.model.with_doc("Customer", row.customer_name, function() {
		var customer = frappe.model.get_doc("Customer", row.customer_name);
		row.customer_group = customer.customer_group;
		refresh_field("customer_group", cdn, "customer_items");
	});
	return true;
}

$.extend(erpnext.item, {
	setup_queries: function(frm) {
		frm.fields_dict['item_group'].get_query = function(doc, cdt, cdn) {
			return {
				filters: [
					['Item Group', 'docstatus', '!=', 2]
				]
			}
		}

		frm.fields_dict['deferred_revenue_account'].get_query = function() {
			return {
				filters: {
					'root_type': 'Liability',
					"is_group": 0
				}
			}
		}

		frm.fields_dict['deferred_expense_account'].get_query = function() {
			return {
				filters: {
					'root_type': 'Asset',
					"is_group": 0
				}
			}
		}

		frm.fields_dict.customer_items.grid.get_field("customer_name").get_query = function(doc, cdt, cdn) {
			return { query: "erpnext.controllers.queries.customer_query" }
		}

		frm.fields_dict.supplier_items.grid.get_field("supplier").get_query = function(doc, cdt, cdn) {
			return { query: "erpnext.controllers.queries.supplier_query" }
		}

		frm.fields_dict.reorder_levels.grid.get_field("warehouse_group").get_query = function(doc, cdt, cdn) {
			return {
				filters: { "is_group": 1 }
			}
		}

		frm.fields_dict.reorder_levels.grid.get_field("warehouse").get_query = function(doc, cdt, cdn) {
			var d = locals[cdt][cdn];

			var filters = {
				"is_group": 0
			}

			if (d.parent_warehouse) {
				filters.extend({"parent_warehouse": d.warehouse_group})
			}

			return {
				filters: filters
			}
		}

		frm.set_query("applicable_to", function (doc, cdt, cdn) {
			if (!doc.__islocal) {
				return {
					filters: { 'name': ['!=', doc.name] }
				}
			}
		});

		frm.set_query("applicable_commission_item", function(doc, cdt, cdn) {
			var filters = {
				"is_stock_item": 0
			  };
			  return erpnext.queries.item(filters);
		});

		frm.set_query("applicable_item_code", "applicable_items", function (doc, cdt, cdn) {
			var filters = {};
			if (!doc.__islocal) {
				filters['name'] = ['!=', doc.name];
			}
			return erpnext.queries.item(filters);
		});

		frm.set_query("applicable_uom", "applicable_items", function(doc, cdt, cdn) {
			let item = frappe.get_doc(cdt, cdn);
			return erpnext.queries.item_uom(item.applicable_item_code);
		});
	},

	make_dashboard: function(frm) {
		if(frm.doc.__islocal)
			return;

		// Show Stock Levels only if is_stock_item
		if (frm.doc.is_stock_item) {
			frappe.require('item-dashboard.bundle.js', function() {
				var section = frm.dashboard.add_section("", "Stock Levels");
				erpnext.item.item_dashboard = new erpnext.stock.ItemDashboard({
					parent: section,
					item_code: frm.doc.name
				});
				erpnext.item.item_dashboard.refresh();
			});
		}
	},

	edit_prices_button: function(frm) {
		frm.add_custom_button(__("Add / Edit Prices"), function() {
			frappe.set_route("query-report", "Item Prices", {"item_code": frm.doc.name});
		}, __("View"));
	},

	weight_to_validate: function(frm){
		if((frm.doc.net_weight || frm.doc.gross_weight) && !frm.doc.weight_uom) {
			frappe.msgprint(__('Weight is mentioned,\nPlease mention "Weight UOM" too'));
			frappe.validated = 0;
		}
	},

	show_modal_for_manufacturers: function(frm) {
		var dialog = new frappe.ui.Dialog({
			fields: [
				{
					fieldtype: 'Link',
					fieldname: 'manufacturer',
					options: 'Manufacturer',
					label: 'Manufacturer',
					reqd: 1,
				},
				{
					fieldtype: 'Data',
					label: 'Manufacturer Part Number',
					fieldname: 'manufacturer_part_no'
				},
			]
		});

		dialog.set_primary_action(__('Create'), function() {
			var data = dialog.get_values();
			if(!data) return;

			// call the server to make the variant
			data.template = frm.doc.name;
			frappe.call({
				method: "erpnext.controllers.item_variant.get_variant",
				args: data,
				callback: function(r) {
					var doclist = frappe.model.sync(r.message);
					dialog.hide();
					frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				}
			});
		})

		dialog.show();
	},

	show_multiple_variants_dialog: function(frm) {
		let me = this;

		let promises = [];
		let attr_val_fields = {};

		function make_fields_from_attribute_values(attr_dict) {
			let fields = [];
			for (let [i, attribute_name] of Object.keys(attr_dict).entries()) {
				// Section Break after 3 columns
				if (i % 3 === 0) {
					fields.push({fieldtype: 'Section Break'});
				}

				// Column Label
				fields.push({fieldtype: 'Column Break', label: attribute_name});

				for (let attribute_value of attr_dict[attribute_name]) {
					fields.push({
						fieldtype: 'Check',
						label: attribute_value,
						fieldname: attribute_value,
						attribute_name: attribute_name,
						attribute_value: attribute_value,
						default: 0,
						onchange: function() {
							let selected_attributes = get_selected_attributes();
							let lengths = [];
							Object.keys(selected_attributes).map(key => {
								lengths.push(selected_attributes[key].length);
							});
							if (lengths.includes(0)) {
								me.multiple_variant_dialog.get_primary_btn().html(__('Create Variants'));
								me.multiple_variant_dialog.disable_primary_action();
							} else {
								let no_of_combinations = lengths.reduce((a, b) => a * b, 1);
								me.multiple_variant_dialog.get_primary_btn()
									.html(__(
										`Make ${no_of_combinations} Variant${no_of_combinations === 1 ? '' : 's'}`
									));
								me.multiple_variant_dialog.enable_primary_action();
							}
						}
					});
				}
			}
			return fields;
		}

		function make_and_show_dialog(fields) {
			me.multiple_variant_dialog = new frappe.ui.Dialog({
				title: __("Select Attribute Values"),
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "help",
						options: `<label class="control-label">
							${__("Select at least one value from each of the attributes.")}
						</label>`,
					}
				].concat(fields)
			});

			me.multiple_variant_dialog.set_primary_action(__('Create Variants'), () => {
				let selected_attributes = get_selected_attributes();

				me.multiple_variant_dialog.hide();
				frappe.call({
					method: "erpnext.controllers.item_variant.enqueue_multiple_variant_creation",
					args: {
						"item": frm.doc.name,
						"args": selected_attributes
					},
					callback: function(r) {
						if (r.message==='queued') {
							frappe.show_alert({
								message: __("Variant creation has been queued."),
								indicator: 'orange'
							});
						} else {
							frappe.show_alert({
								message: __("{0} variants created.", [r.message]),
								indicator: 'green'
							});
						}
					}
				});
			});

			$($(me.multiple_variant_dialog.$wrapper.find('.form-column'))
				.find('.frappe-control')).css('margin-bottom', '0px');

			me.multiple_variant_dialog.disable_primary_action();
			me.multiple_variant_dialog.clear();
			me.multiple_variant_dialog.show();
		}

		function get_selected_attributes() {
			let selected_attributes = {};

			let value_fields = me.multiple_variant_dialog.fields.filter(f => f.attribute_name && f.attribute_value);
			for (let df of value_fields) {
				if (!me.multiple_variant_dialog.get_value(df.fieldname)) {
					continue;
				}

				if (!selected_attributes[df.attribute_name]) {
					selected_attributes[df.attribute_name] = [];
				}

				selected_attributes[df.attribute_name].push(df.attribute_value);
			}

			return selected_attributes;
		}

		frm.doc.attributes.forEach(function(d) {
			let p = new Promise(resolve => {
				if(!d.numeric_values) {
					frappe.call({
						method: "frappe.client.get_list",
						args: {
							doctype: "Item Attribute Value",
							filters: [
								["parent","=", d.attribute]
							],
							fields: ["attribute_value"],
							limit_start: 0,
							limit_page_length: 500,
							parent: "Item Attribute",
							order_by: "idx"
						}
					}).then((r) => {
						if(r.message) {
							attr_val_fields[d.attribute] = r.message.map(function(d) { return d.attribute_value; });
							resolve();
						}
					});
				} else {
					frappe.call({
						method: "frappe.client.get",
						args: {
							doctype: "Item Attribute",
							name: d.attribute
						}
					}).then((r) => {
						if(r.message) {
							const from = r.message.from_range;
							const to = r.message.to_range;
							const increment = r.message.increment;

							let values = [];
							for(var i = from; i <= to; i += increment) {
								values.push(i);
							}
							attr_val_fields[d.attribute] = values;
							resolve();
						}
					});
				}
			});

			promises.push(p);

		}, this);

		Promise.all(promises).then(() => {
			let fields = make_fields_from_attribute_values(attr_val_fields);
			make_and_show_dialog(fields);
		})

	},

	show_single_variant_dialog: function(frm) {
		var fields = []

		for(var i=0;i< frm.doc.attributes.length;i++){
			var fieldtype, desc;
			var row = frm.doc.attributes[i];
			if (row.numeric_values){
				fieldtype = "Float";
				desc = "Min Value: "+ row.from_range +" , Max Value: "+ row.to_range +", in Increments of: "+ row.increment
			}
			else {
				fieldtype = "Data";
				desc = ""
			}
			fields = fields.concat({
				"label": row.attribute,
				"fieldname": row.attribute,
				"fieldtype": fieldtype,
				"reqd": 0,
				"description": desc
			})
		}

		var d = new frappe.ui.Dialog({
			title: __('Create Variant'),
			fields: fields
		});

		d.set_primary_action(__('Create'), function() {
			var args = d.get_values();
			if(!args) return;
			frappe.call({
				method: "erpnext.controllers.item_variant.get_variant",
				btn: d.get_primary_btn(),
				args: {
					"template": frm.doc.name,
					"args": d.get_values()
				},
				callback: function(r) {
					// returns variant item
					if (r.message) {
						var variant = r.message;
						frappe.msgprint_dialog = frappe.msgprint(__("Item Variant {0} already exists with same attributes",
							[repl('<a href="/app/item/%(item_encoded)s" class="strong variant-click">%(item)s</a>', {
								item_encoded: encodeURIComponent(variant),
								item: variant
							})]
						));
						frappe.msgprint_dialog.hide_on_page_refresh = true;
						frappe.msgprint_dialog.$wrapper.find(".variant-click").on("click", function() {
							d.hide();
						});
					} else {
						d.hide();
						frappe.call({
							method: "erpnext.controllers.item_variant.create_variant",
							args: {
								"item": frm.doc.name,
								"args": d.get_values()
							},
							callback: function(r) {
								var doclist = frappe.model.sync(r.message);
								frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
							}
						});
					}
				}
			});
		});

		d.show();

		$.each(d.fields_dict, function(i, field) {

			if(field.df.fieldtype !== "Data") {
				return;
			}

			$(field.input_area).addClass("ui-front");

			var input = field.$input.get(0);
			input.awesomplete = new Awesomplete(input, {
				minChars: 0,
				maxItems: 99,
				autoFirst: true,
				list: [],
			});
			input.field = field;

			field.$input
				.on('input', function(e) {
					var term = e.target.value;
					frappe.call({
						method: "erpnext.stock.doctype.item.item.get_item_attribute",
						args: {
							parent: i,
							attribute_value: term
						},
						callback: function(r) {
							if (r.message) {
								e.target.awesomplete.list = r.message.map(function(d) { return d.attribute_value; });
							}
						}
					});
				})
				.on('focus', function(e) {
					$(e.target).val('').trigger('input');
				})
		});
	},

	toggle_attributes: function(frm) {
		let grid = frm.fields_dict.attributes.grid;
		grid.update_docfield_property("attribute_value", "in_list_view", cint(!!frm.doc.variant_of));
		grid.reset_grid();
	},

	change_uom: function (frm) {
		var dialog = new frappe.ui.Dialog({
			title: "Edit UOM",
			fields: [
				{
					label:__("New Default UOM"),
					fieldname: "stock_uom",
					fieldtype: "Link",
					options: "UOM",
					default: frm.doc.stock_uom,
					description: __('Will update Default UOM in all transactions and prices')
				},
				{
					label:__("New Contents UOM"),
					fieldname: "alt_uom",
					fieldtype: "Link",
					options: "UOM",
					default: frm.doc.alt_uom,
					description: __('Will update Contents UOM in all transactions')
				},
				{
					label: __("New Per Unit"),
					fieldname: "alt_uom_size",
					fieldtype: "Float",
					default: frm.doc.alt_uom_size,
					description: __('Will NOT update Per Unit and Contents Qty in transactions')
				}
			],
		});

		dialog.set_primary_action(__("Update"), function() {
			var values = dialog.get_values();
			frappe.call({
				method: "erpnext.stock.doctype.item.item.change_uom",
				freeze: 1,
				args: {
					"item_code": frm.doc.name,
					"stock_uom": cstr(values.stock_uom),
					"alt_uom": cstr(values.alt_uom),
					"alt_uom_size": cstr(values.alt_uom_size),
				},
				callback: function(r) {
					if (!r.exc) {
						frm.reload_doc();
					}
					dialog.hide();
				}
			});
		});

		dialog.show();
	}
});

frappe.ui.form.on("UOM Conversion Detail", {
	uom: function(frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if (row.uom) {
			frappe.call({
				method: "erpnext.stock.doctype.item.item.get_uom_conv_factor",
				args: {
					"from_uom": row.uom,
					"to_uom": frm.doc.stock_uom
				},
				callback: function(r) {
					if (!r.exc && r.message) {
						frappe.model.set_value(cdt, cdn, "conversion_factor", r.message);
					}
				}
			});
		}
	}
});

frappe.ui.form.on('Item Applicable Item', {
	applicable_item_code: function (frm, cdt, cdn) {
		var row = frappe.get_doc(cdt, cdn);
		if (!row.applicable_item_code) {
			frappe.model.set_value(cdt, cdn, 'applicable_item_name', null);
			frappe.model.set_value(cdt, cdn, 'applicable_item_group', null);
		}
	},
});
