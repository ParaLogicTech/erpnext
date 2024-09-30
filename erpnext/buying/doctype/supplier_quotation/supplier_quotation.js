// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

// attach required files
{% include 'erpnext/public/js/controllers/buying.js' %};

erpnext.buying.SupplierQuotationController = class SupplierQuotationController extends erpnext.buying.BuyingController {
	setup() {
		this.frm.custom_make_buttons = {
			'Purchase Order': 'Purchase Order',
			'Quotation': 'Quotation',
			'Subscription': 'Subscription'
		}

		super.setup();
	}

	refresh() {
		let me = this;
		super.refresh();
		if (this.frm.doc.docstatus === 1) {
			if (frappe.model.can_create("Purchase Order")) {
				this.frm.add_custom_button(__("Purchase Order"), this.make_purchase_order,
					__('Create'));
			}

			if (frappe.model.can_create("Quotation")) {
				this.frm.add_custom_button(__("Quotation"), this.make_quotation,
					__('Create'));
			}

			this.frm.page.set_inner_btn_group_as_primary(__('Create'));

			if(!this.frm.doc.auto_repeat && frappe.model.can_create("Auto Repeat")) {
				this.frm.add_custom_button(__('Subscription'), function() {
					erpnext.utils.make_subscription(me.frm.doc.doctype, me.frm.doc.name)
				}, __('Create'))
			}
		} else if (this.frm.doc.docstatus===0) {
			if (frappe.model.can_read("Material Request")) {
				this.frm.add_custom_button(__('Material Request'),
					function () {
						erpnext.utils.map_current_doc({
							method: "erpnext.stock.doctype.material_request.material_request.make_supplier_quotation",
							source_doctype: "Material Request",
							target: me.frm,
							setters: {
								company: me.frm.doc.company
							},
							get_query_filters: {
								material_request_type: "Purchase",
								docstatus: 1,
								status: ["!=", "Stopped"],
								per_ordered: ["<", 99.99]
							}
						})
					}, __("Get Items From"));
			}
		}
	}

	make_purchase_order() {
		frappe.model.open_mapped_doc({
			method: "erpnext.buying.doctype.supplier_quotation.supplier_quotation.make_purchase_order",
			frm: cur_frm
		})
	}
	make_quotation() {
		frappe.model.open_mapped_doc({
			method: "erpnext.buying.doctype.supplier_quotation.supplier_quotation.make_quotation",
			frm: cur_frm
		})

	}
};

// for backward compatibility: combine new and previous states
extend_cscript(cur_frm.cscript, new erpnext.buying.SupplierQuotationController({frm: cur_frm}));

cur_frm.fields_dict['items'].grid.get_field('project').get_query =
	function(doc, cdt, cdn) {
		return{
			filters:[
				['Project', 'status', 'not in', 'Completed, Cancelled']
			]
		}
	}
