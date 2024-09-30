// Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.provide("erpnext.vehicles");

erpnext.vehicles.VehicleGatePass = class VehicleGatePass extends erpnext.vehicles.VehicleTransactionController {
	refresh() {
		super.refresh();
	}

	setup_queries() {
		super.setup_queries();

		let me = this;

		me.frm.set_query("project", function() {
			var filters = {};

			filters['vehicle_status'] = 'In Workshop';

			return {
				filters: filters
			};
		});

		me.frm.set_query("sales_invoice", function() {
			return {
				filters: {
					project: me.frm.doc.project,
					docstatus:  ['<', 2]
				}
			};
		});

		me.frm.set_query("vehicle_delivery", function() {
			return {
				filters: {
					vehicle_booking_order: me.frm.doc.vehicle_booking_order,
					docstatus: ['=', 1],
					is_return: 0,
				}
			};
		});

		me.frm.set_query("vehicle_booking_order", function() {
			return {
				filters: {
					docstatus: ['=', 1],
					status: ['!=', 'Cancelled Booking'],
				}
			 };
		});

		me.frm.set_query("opportunity", function() {
			return {
				filters: {
					conversion_document: "Order",
				}
			};
		});
	}

	get_customer_details() {
		let me = this;

		let args = {
			doctype: me.frm.doc.doctype,
			company: me.frm.doc.company,
			customer: me.frm.doc.customer,
			posting_date: me.frm.doc.posting_date
		}

		if (["Service - Vehicle Delivery", "Service - Test Drive"].includes(me.frm.doc.purpose)) {
			args.project = me.frm.doc.project;
		}

		if (me.frm.doc.purpose == "Sales - Vehicle Delivery") {
			args.vehicle_booking_order = me.frm.doc.vehicle_booking_order;
			args.vehicle_delivery = me.frm.doc.vehicle_delivery;
		}

		if (me.frm.doc.purpose == "Sales - Test Drive") {
			args.opportunity = me.frm.doc.opportunity;
			args.lead = me.frm.doc.lead;
		}

		return frappe.call({
			method: "erpnext.vehicles.vehicle_transaction_controller.get_customer_details",
			args: {
				args: args
			},
			callback: function (r) {
				if (r.message && !r.exc) {
					return me.frm.set_value(r.message);
				}
			}
		});
	}

	lead() {
		if (this.frm.doc.purpose != "Sales - Test Drive") {
			this.frm.doc.lead = null;
			return;
		}
		return this.get_customer_details();
	}

	opportunity() {
		let me = this;

		if (me.frm.doc.purpose != "Sales - Test Drive") {
			me.frm.doc.opportunity = null;
			return;
		}

		if (me.frm.doc.opportunity) {
			return frappe.call({
				method: "erpnext.vehicles.doctype.vehicle_gate_pass.vehicle_gate_pass.get_opportunity_details",
				args: {
					"opportunity": me.frm.doc.opportunity,
				},
				callback: function (r) {
					if (r.message && !r.exc) {
						return me.frm.set_value(r.message);
					}
				}
			});
		}
	}

	vehicle_delivery() {
		let me = this;

		if (me.frm.doc.purpose != "Sales - Vehicle Delivery") {
			me.frm.doc.vehicle_delivery = null;
			return;
		}

		if (me.frm.doc.vehicle_delivery) {
			return frappe.call({
				method: "erpnext.vehicles.doctype.vehicle_gate_pass.vehicle_gate_pass.get_vehicle_delivery_details",
				args: {
					"vehicle_delivery": me.frm.doc.vehicle_delivery,
				},
				callback: function (r) {
					if (r.message && !r.exc) {
						return me.frm.set_value(r.message);
					}
				}
			});
		}
	}

	vehicle_booking_order() {
		if (this.frm.doc.purpose != "Sales - Vehicle Delivery") {
			this.frm.doc.vehicle_booking_order = null;
			return;
		}

		return super.vehicle_booking_order();
	}
};

extend_cscript(cur_frm.cscript, new erpnext.vehicles.VehicleGatePass({frm: cur_frm}));
