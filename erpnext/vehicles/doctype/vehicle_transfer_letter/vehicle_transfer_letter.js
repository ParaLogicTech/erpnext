// Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.provide("erpnext.vehicles");
erpnext.vehicles.VehicleTransferLetterController = class VehicleTransferLetterController extends erpnext.vehicles.VehicleTransactionController {
	refresh() {
		super.refresh();
	}

	setup_queries() {
		super.setup_queries();

		this.frm.set_query("vehicle_booking_order", function() {
			return {
				filters: {
					status: ['!=', 'Cancelled Booking'],
					docstatus: 1,
				}
			};
		});
	}

	customer() {
		super.customer();
		this.warn_vehicle_reserved();
	}

	vehicle() {
		super.vehicle();
		this.warn_vehicle_reserved();
		this.warn_vehicle_reserved_by_sales_person();
	}

	sales_person() {
		this.warn_vehicle_reserved_by_sales_person();
	}

	warn_vehicle_reserved() {
		if (this.frm.doc.vehicle && this.frm.doc.customer) {
			frappe.call({
				method: "erpnext.vehicles.doctype.vehicle.vehicle.warn_vehicle_reserved",
				args: {
					vehicle: this.frm.doc.vehicle,
					customer: this.frm.doc.customer
				}
			})
		}
	}

	warn_vehicle_reserved_by_sales_person() {
		if (this.frm.doc.vehicle && this.frm.doc.sales_person) {
			frappe.call({
				method: "erpnext.vehicles.doctype.vehicle.vehicle.warn_vehicle_reserved_by_sales_person",
				args: {
					vehicle: this.frm.doc.vehicle,
					sales_person: this.frm.doc.sales_person
				}
			})
		}
	}
};

extend_cscript(cur_frm.cscript, new erpnext.vehicles.VehicleTransferLetterController({frm: cur_frm}));
