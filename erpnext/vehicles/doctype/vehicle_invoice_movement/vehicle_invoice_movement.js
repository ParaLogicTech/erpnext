// Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.provide("erpnext.vehicles");
erpnext.vehicles.VehicleInvoiceMovementController = class VehicleInvoiceMovementController extends erpnext.vehicles.VehicleTransactionController {
	refresh() {
		super.refresh();
		this.frm.trigger('set_fields_read_only');
	}

	purpose() {
		this.frm.trigger('set_fields_read_only');
	}

	setup_queries() {
		super.setup_queries();

		var me = this;
		me.frm.set_query("vehicle", "invoices", function () {
			var filters = {};

			me.set_invoice_filter(filters);

			if (me.frm.doc.supplier) {
				filters['supplier'] = ['in', ['', me.frm.doc.supplier]];
			}

			return {
				filters: filters
			}
		});

		me.frm.set_query("vehicle_booking_order", "invoices", function () {
			var filters = {};

			me.set_invoice_filter(filters);

			filters['status'] = ['!=', 'Cancelled Booking'];
			filters['docstatus'] = 1;

			return {
				filters: filters
			};
		});
	}

	set_invoice_filter(filters) {
		if (this.frm.doc.purpose == "Receive") {
			filters['invoice_status'] = 'Not Received';
		} else if (this.frm.doc.purpose == "Return") {
			filters['invoice_status'] = 'Issued';
			if (this.frm.doc.issued_for) {
				filters['invoice_issued_for'] = this.frm.doc.issued_for;
			}
		} else {
			filters['invoice_status'] = 'In Hand';
		}
	}

	set_fields_read_only() {
		let enabled = reqd = cint(this.frm.doc.purpose == "Receive");

		for (let fn of ['bill_no', 'bill_date']) {
			this.frm.fields_dict.invoices.grid.toggle_reqd(fn, reqd);
			this.frm.fields_dict.invoices.grid.toggle_enable(fn, enabled);
		}
	}
};

extend_cscript(cur_frm.cscript, new erpnext.vehicles.VehicleInvoiceMovementController({frm: cur_frm}));
