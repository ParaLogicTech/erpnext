frappe.provide('frappe.ui.form');

frappe.ui.form.CustomerQuickEntryForm = class CustomerQuickEntryForm extends frappe.ui.form.QuickEntryForm {
	skip_redirect_on_error = true

	render_dialog() {
		let additional_fields = this.get_customer_fields();
		let additional_fieldnames = additional_fields.map(f => f.fieldname);
		this.mandatory = this.mandatory.filter(f => !additional_fieldnames.includes(f.fieldname));
		this.mandatory = this.mandatory.concat(additional_fields);
		super.render_dialog();
		this.setup_events();
	}

	setup_events() {
		let me = this;

		if (me.dialog.fields_dict["customer_group"]) {
			me.dialog.fields_dict["customer_group"].df.get_query = {'disable_selection': 0};

			me.dialog.fields_dict["customer_group"].df.onchange = () => {
				erpnext.utils.set_customer_overrides(me.dialog);
			};
		}

		if (me.dialog.fields_dict["tax_id"]) {
			me.dialog.fields_dict["tax_id"].df.onchange = () => {
				var value = me.dialog.get_value('tax_id');
				value = frappe.regional.get_formatted_tax_id(value);
				me.dialog.doc.tax_id = value;
				me.dialog.get_field('tax_id').refresh();
				frappe.regional.validate_duplicate_tax_id(me.dialog.doc, "tax_id");
			};
		}

		if (me.dialog.fields_dict["tax_cnic"]) {
			me.dialog.fields_dict["tax_cnic"].df.onchange = () => {
				var value = me.dialog.get_value('tax_cnic');
				value = frappe.regional.get_formatted_cnic(value);
				me.dialog.doc.tax_cnic = value;
				me.dialog.get_field('tax_cnic').refresh();
				frappe.regional.validate_duplicate_tax_id(me.dialog.doc, "tax_cnic");
			};
		}

		if (me.dialog.fields_dict["tax_strn"]) {
			me.dialog.fields_dict["tax_strn"].df.onchange = () => {
				var value = me.dialog.get_value('tax_strn');
				value = frappe.regional.get_formatted_strn(value);
				me.dialog.doc.tax_strn = value;
				me.dialog.get_field('tax_strn').refresh();
				frappe.regional.validate_duplicate_tax_id(me.dialog.doc, "tax_strn");
			};
		}

		if (me.dialog.fields_dict["mobile_no"]) {
			me.dialog.fields_dict["mobile_no"].df.onchange = () => {
				var value = me.dialog.get_value('mobile_no');
				value = frappe.regional.get_formatted_mobile_no(value)
				me.dialog.doc.mobile_no = value;
				me.dialog.get_field('mobile_no').refresh();
				frappe.regional.validate_duplicate_mobile_no(me.dialog.doc, "mobile_no");
			};
		}

		if (me.dialog.fields_dict["mobile_no_2"]) {
			me.dialog.fields_dict["mobile_no_2"].df.onchange = () => {
				var value = me.dialog.get_value('mobile_no_2');
				value = frappe.regional.get_formatted_mobile_no(value);
				me.dialog.doc.mobile_no_2 = value;
				me.dialog.get_field('mobile_no_2').refresh();
			};
		}
	}

	get_customer_fields() {
		return [
			{
				fieldtype: "Section Break",
				label: __("Primary Contact Person"),
				depends_on: "eval:doc.customer_type == 'Company'"
			},
			{
				label: __("Salutation"),
				fieldname: "salutation",
				fieldtype: "Link",
				options: "Salutation",
			},
			{
				fieldtype: "Column Break"
			},
			{
				label: __("First Name"),
				fieldname: "contact_first_name",
				fieldtype: "Data",
			},
			{
				fieldtype: "Column Break"
			},
			{
				label: __("Last Name"),
				fieldname: "contact_last_name",
				fieldtype: "Data",
			},
			{
				fieldtype: "Section Break",
				label: __("Primary Contact Details"),
			},
			{
				label: __("Mobile No (Primary)"),
				fieldname: "mobile_no",
				fieldtype: "Data"
			},
			{
				fieldtype: "Column Break"
			},
			{
				label: __("Mobile No (Secondary"),
				fieldname: "mobile_no_2",
				fieldtype: "Data"
			},
			{
				fieldtype: "Column Break"
			},
			{
				label: __("Landline No"),
				fieldname: "phone_no",
				fieldtype: "Data"
			},
			{
				fieldtype: "Column Break"
			},
			{
				label: __("Email Id"),
				fieldname: "email_id",
				fieldtype: "Data"
			},
			{
				fieldtype: "Section Break",
				label: __("Primary Address Details"),
			},
			{
				label: __("Address Line 1"),
				fieldname: "address_line1",
				fieldtype: "Data"
			},
			{
				label: __("Address Line 2"),
				fieldname: "address_line2",
				fieldtype: "Data"
			},
			{
				label: __("ZIP Code"),
				fieldname: "pincode",
				fieldtype: "Data"
			},
			{
				fieldtype: "Column Break"
			},
			{
				label: __("City"),
				fieldname: "city",
				fieldtype: "Data"
			},
			{
				label: __("State"),
				fieldname: "state",
				fieldtype: "Data"
			},
			{
				label: __("Country"),
				fieldname: "country",
				fieldtype: "Link",
				options: "Country"
			},
			{
				label: __("Customer POS Id"),
				fieldname: "customer_pos_id",
				fieldtype: "Data",
				hidden: 1
			}];
	}
};