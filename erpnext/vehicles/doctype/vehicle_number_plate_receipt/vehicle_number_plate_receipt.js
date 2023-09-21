// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.provide("erpnext.vehicles");
erpnext.vehicles.VehicleNumberPlateReceiptController = class VehicleNumberPlateReceiptController extends erpnext.vehicles.VehicleTransactionController {
	setup_queries() {
		super.setup_queries();

		this.frm.set_query("vehicle_booking_order", "number_plates", function () {
			return {
				filters: {
					status: ['!=', 'Cancelled Booking'],
					docstatus: 1
				}
			};
		});
	}
};

extend_cscript(cur_frm.cscript, new erpnext.vehicles.VehicleNumberPlateReceiptController({frm: cur_frm}));
