// Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.provide("erpnext.vehicles");

erpnext.vehicles.VehicleGatePass = class VehicleGatePass extends erpnext.vehicles.VehicleTransactionController {
	refresh() {
		super.refresh();
	}

	setup_queries() {
		super.setup_queries();

		var me = this;

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
					item_code : me.frm.doc.item_code,
					docstatus: ['=', 1]
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
	}

	get_customer_details() {
		var me = this;

		let args = {
			doctype: me.frm.doc.doctype,
			company: me.frm.doc.company,
			vehicle_owner: me.frm.doc.vehicle_owner,
			posting_date: me.frm.doc.posting_date
		}

		if (me.frm.doc.purpose == "Service - Vehicle Delivery" || me.frm.doc.purpose == "Service - Test Drive" ) {
			args.project = me.frm.doc.project;
		}

		if (me.frm.doc.purpose == "Sales - Vehicle Delivery") {
			args.vehicle_booking_order = me.frm.doc.vehicle_booking_order;
		}

		if (me.frm.doc.purpose == "Sales - Test Drive") {
			args.opportunity = me.frm.doc.opportunity;
		}

		return frappe.call({
			method: "erpnext.vehicles.vehicle_transaction_controller.get_customer_details",
			args: {
				args: args
			},
			callback: function (r) {
				if (r.message && !r.exc) {
					me.frm.set_value(r.message);
				}
			}
		});
	}


	opportunity() {
		this.frm.set_value("customer", null);
		this.frm.set_value("lead", null);
		frappe.call({
			method: "erpnext.vehicles.doctype.vehicle_gate_pass.vehicle_gate_pass.get_opportunity_details",
			args: {
				"opportunity": this.frm.doc.opportunity,
			},
			callback: function (r) {
				if (r.message && !r.exc) {
					me.frm.set_value(r.message);
				}
			}
		})
	}

	lead() {
		frappe.call({
			method: "erpnext.crm.doctype.lead.lead.get_lead_details",
			args: {
				"lead": this.frm.doc.lead,
			},
			callback: function (r) {
				if (r.message && !r.exc) {
					me.frm.set_value(r.message);
				}
			}
		})
	}

	vehicle_booking_order(doc) {
		if (doc.purpose != "Sales - Vehicle Delivery") {
			this.frm.set_value("vehicle_booking_order", this.frm.doc.vehicle_booking_order = null);
			return;
		}

		var me = this;

		return frappe.call({
			method: "erpnext.vehicles.vehicle_transaction_controller.get_vehicle_booking_order_details",
			args: {
				args: {
					doctype: me.frm.doc.doctype,
					company: me.frm.doc.company,
					customer: me.frm.doc.customer,
					supplier: me.frm.doc.supplier,
					vehicle_booking_order: doc.vehicle_booking_order,
					project: doc.project,
					vehicle: doc.vehicle,
					get_vehicle_delivery: true,
					posting_date: me.frm.doc.posting_date || me.frm.doc.transaction_date,
					issued_for: me.frm.doc.issued_for,
				}
			},
			callback: function (r) {
				if (r.message && !r.exc) {
					me.frm.set_value(r.message);
				}
			}
		});
	}
};

extend_cscript(cur_frm.cscript, new erpnext.vehicles.VehicleGatePass({frm: cur_frm}));
