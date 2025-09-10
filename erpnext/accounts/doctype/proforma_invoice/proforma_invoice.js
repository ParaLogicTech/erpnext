{% include 'erpnext/selling/sales_common.js' %}

frappe.provide("erpnext.accounts");

erpnext.accounts.ProformaInvoiceController = class ProformaInvoiceController extends erpnext.selling.SellingController {
	setup() {
		super.setup();

		this.frm.custom_make_buttons = {
			'Sales Invoice': 'Sales Invoice',
			'Payment Request': 'Payment Request',
			'Payment Entry': 'Payment',
		};

		this.setup_queries();
	}

	refresh(doc, dt, dn) {
		super.refresh(doc, dt, dn);
		this.setup_buttons();
	}

	setup_buttons() {
		if (this.frm.doc.docstatus == 0) {
			this.add_get_latest_price_button();

			if (frappe.model.can_read("Delivery Note")) {
				this.frm.add_custom_button(__('Delivery Note'), () => {
					this.get_items_from_delivery_note();
				}, __("Get Items From"));
			}

			if (frappe.model.can_read("Sales Order")) {
				this.frm.add_custom_button(__('Sales Order'), () => {
					this.get_items_from_sales_order();
				}, __("Get Items From"));
			}
		}

		if (this.frm.doc.docstatus == 1 && this.frm.doc.status != "Closed") {
			if (flt(this.frm.doc.per_billed) < 100 && frappe.model.can_create("Sales Invoice")) {
				this.frm.add_custom_button(__('Sales Invoice'), () => this.make_sales_invoice(),
					__('Create'));
			}

			if (flt(this.frm.doc.per_billed) == 0) {
				if (frappe.model.can_create("Payment Request")) {
					this.frm.add_custom_button(__('Payment Request'), () => this.make_payment_request(),
						__('Create'));
				}

				if (frappe.model.can_create("Payment Entry") || frappe.model.can_create("Journal Entry")) {
					this.frm.add_custom_button(__('Payment'), () => this.make_payment_entry(true),
						__('Create'));
				}
			}
		}

		if (!this.frm.doc.__islocal && this.frm.doc.docstatus == 1) {
			this.frm.page.set_inner_btn_group_as_primary(__('Create'));
		}
	}

	get_items_from_sales_order() {
		var me = this;

		erpnext.utils.map_current_doc({
			method: "erpnext.selling.doctype.sales_order.sales_order.make_proforma_invoice",
			source_doctype: "Sales Order",
			target: me.frm,
			setters: [
				{
					fieldtype: 'Link',
					label: __('Customer'),
					options: 'Customer',
					fieldname: 'customer',
					default: me.frm.doc.customer || undefined,
				},
				{
					fieldtype: 'Link',
					label: __('Project'),
					options: 'Project',
					fieldname: 'project',
					default: me.frm.doc.project || undefined,
				},
				{
					fieldtype: 'Link',
					label: __('Branch'),
					options: 'Branch',
					fieldname: 'branch',
					default: me.frm.doc.branch || undefined,
				},
				{
					fieldtype: 'DateRange',
					label: __('Date Range'),
					fieldname: 'transaction_date',
				}
			],
			columns: ['customer_name', 'transaction_date', 'project'],
			get_query: function() {
				var filters = {
					company: me.frm.doc.company,
					claim_billing: 0,
				};
				if (me.frm.doc.customer) {
					filters["customer"] = me.frm.doc.customer;
				}

				return {
					query: "erpnext.controllers.queries.get_sales_orders_to_be_billed",
					filters: filters
				};
			},
		});
	}

	get_items_from_delivery_note() {
		var me = this;

		erpnext.utils.map_current_doc({
			method: "erpnext.stock.doctype.delivery_note.delivery_note.make_proforma_invoice",
			source_doctype: "Delivery Note",
			target: me.frm,
			setters: [
				{
					fieldtype: 'Link',
					label: __('Customer'),
					options: 'Customer',
					fieldname: 'customer',
					default: me.frm.doc.customer || undefined,
				},
				{
					fieldtype: 'Link',
					label: __('Project'),
					options: 'Project',
					fieldname: 'project',
					default: me.frm.doc.project || undefined,
				},
				{
					fieldtype: 'Link',
					label: __('Branch'),
					options: 'Branch',
					fieldname: 'branch',
					default: me.frm.doc.branch || undefined,
				},
				{
					fieldtype: 'DateRange',
					label: __('Date Range'),
					fieldname: 'posting_date',
				}
			],
			columns: ['customer_name', 'posting_date', 'project'],
			get_query: function() {
				var filters = {
					company: me.frm.doc.company,
					is_return: 0,
					claim_billing: 0,
				};
				if(me.frm.doc.customer) {
					filters["customer"] = me.frm.doc.customer;
				}

				return {
					query: "erpnext.controllers.queries.get_delivery_notes_to_be_billed",
					filters: filters
				};
			},
		});
	}

	make_sales_invoice() {
		frappe.model.open_mapped_doc({
			method: "erpnext.accounts.doctype.proforma_invoice.proforma_invoice.make_sales_invoice",
			frm: this.frm
		})
	}

	allocated_amount() {
		this.calculate_total_advance();
		this.calculate_outstanding_amount();
		this.frm.refresh_fields();
	}

	advances_remove() {
		this.allocated_amount();
	}
};

cur_frm.script_manager.make(erpnext.accounts.ProformaInvoiceController);
