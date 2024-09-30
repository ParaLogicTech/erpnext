frappe.provide('frappe.ui.form');

frappe.ui.form.VehicleQuickEntryForm = class VehicleQuickEntryForm extends frappe.ui.form.QuickEntryForm {
	init(doctype, after_insert) {
		this.skip_redirect_on_error = true;
		super.init(doctype, after_insert);
	}

	render_dialog() {
		super.render_dialog();
		this.init_post_render_dialog_operations();
	}

	init_post_render_dialog_operations() {
		var me = this;

		me.dialog.fields_dict["engine_no"].df.onchange = () => {
			var value = me.dialog.get_value('engine_no');
			value = erpnext.utils.get_formatted_vehicle_id(value);
			me.dialog.doc.engine_no = value;
			me.dialog.get_field('engine_no').refresh();
			erpnext.utils.validate_duplicate_vehicle(me.dialog.doc, "engine_no");
		};

		me.dialog.fields_dict["chassis_no"].df.onchange = () => {
			var value = me.dialog.get_value('chassis_no');
			value = erpnext.utils.get_formatted_vehicle_id(value);
			me.dialog.doc.chassis_no = value;
			me.dialog.get_field('chassis_no').refresh();
			erpnext.utils.validate_duplicate_vehicle(me.dialog.doc, "chassis_no");
		};

		me.dialog.fields_dict["license_plate"].df.onchange = () => {
			var value = me.dialog.get_value('license_plate');
			value = erpnext.utils.get_formatted_vehicle_id(value);
			me.dialog.doc.license_plate = value;
			me.dialog.get_field('license_plate').refresh();
			erpnext.utils.validate_duplicate_vehicle(me.dialog.doc, "license_plate");
		};

		me.dialog.get_field("item_code").get_query = function () {
			return {
				query: "erpnext.controllers.queries.item_query",
				filters: {'is_vehicle': 1}
			};
		}
		
		me.dialog.fields_dict["item_code"].df.onchange = () => {
			var item_code = me.dialog.get_value('item_code');
			if (item_code) {
				frappe.db.get_value("Item", item_code, "item_name", (r) => {
					if (r) {
						me.dialog.doc.item_name = r.item_name;
						me.dialog.get_field('item_name').refresh();
					}
				});
			} else {
				me.dialog.set_value('item_name', '');
			}
		};
		me.dialog.fields_dict["item_code"].df.onchange();

		var insurance_field = me.dialog.get_field("insurance_company");
		if (insurance_field) {
			insurance_field.get_query = function () {
				return {
					query: "erpnext.controllers.queries.customer_query",
					filters: {
						'is_insurance_company': 1
					}
				}
			}
		}

		me.dialog.get_field("color").get_query = function () {
			return erpnext.queries.vehicle_color({item_code: me.dialog.get_value('item_code')});
		}
	}
};
