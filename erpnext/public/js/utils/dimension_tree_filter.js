frappe.provide("erpnext.accounts");

// Reports and financial statements read the dimension list from here
erpnext.dimension_filters = frappe.boot.accounting_dimensions || [];

// Forms opt in by calling setup_dimension_filters on load and set_default_dimensions on company change.
// New documents get their defaults through the company trigger, which frappe runs for link fields with default values.
// Mapped, duplicated and amended documents don't run that trigger, so they keep the dimensions they were created with.
// Master and config doctypes (POS Profile, Budget, ...) don't call set_default_dimensions at all.
// Cost Center and Project are not handled here.
erpnext.accounts.dimensions = {
	get accounting_dimensions() {
		return frappe.boot.accounting_dimensions || [];
	},

	get default_dimensions() {
		return frappe.boot.default_accounting_dimensions || {};
	},

	setup_dimension_filters(frm) {
		for (let dimension of this.accounting_dimensions) {
			frappe.model.with_doctype(dimension.document_type, () => {
				if (frappe.meta.has_field(frm.doctype, dimension.fieldname)) {
					this.set_dimension_query(frm, dimension);
				}

				for (let df of frappe.meta.get_docfields(frm.doctype)) {
					if (df.fieldtype === "Table" && frappe.meta.has_field(df.options, dimension.fieldname)) {
						this.set_dimension_query(frm, dimension, df.fieldname);
					}
				}
			});
		}
	},

	set_dimension_query(frm, dimension, parentfield) {
		let field = parentfield
			? frm.fields_dict[parentfield]?.grid?.get_field(dimension.fieldname)
			: frm.fields_dict[dimension.fieldname];

		// Leave queries the form set itself alone, e.g. Vehicle filtered by customer
		if (!field || field.get_query || field.df?.get_query) {
			return;
		}

		let has_is_group = frappe.meta.has_field(dimension.document_type, "is_group");
		let has_disabled = frappe.meta.has_field(dimension.document_type, "disabled");
		let has_company = frappe.meta.has_field(dimension.document_type, "company");

		if (!(has_is_group || has_disabled || has_company)) {
			return;
		}

		let get_query = (doc) => {
			let filters = {};
			if (has_is_group) {
				filters.is_group = 0;
			}
			if (has_disabled) {
				filters.disabled = 0;
			}
			// Records without a company (e.g. shared across companies) stay selectable
			if (has_company && doc.company) {
				filters.company = ["in", [doc.company, ""]];
			}
			return { filters: filters };
		};

		if (parentfield) {
			frm.set_query(dimension.fieldname, parentfield, get_query);
		} else {
			frm.set_query(dimension.fieldname, get_query);
		}
	},

	set_default_dimensions(frm) {
		let company_defaults = this.default_dimensions[frm.doc.company];
		if (!frm.is_new() || !company_defaults) {
			return;
		}

		// don't set default dimensions if any of the dimension is already set due to mapping
		if (frm.doc.__onload?.load_after_mapping) {
			for (const dimension of this.accounting_dimensions) {
				if (frm.doc[dimension.fieldname]) {
					return;
				}
			}
		}

		for (let dimension of this.accounting_dimensions) {
			let default_dimension = company_defaults[dimension.fieldname];
			if (default_dimension && frappe.meta.has_field(frm.doctype, dimension.fieldname)) {
				frm.set_value(dimension.fieldname, default_dimension);
			}
		}
	},
};
