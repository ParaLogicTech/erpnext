// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext.projects");

erpnext.projects.Timesheet = class Timesheet extends frappe.ui.form.Controller {
	setup() {
		frappe.require("/assets/erpnext/js/projects/timer.js");
		this.frm.ignore_doctypes_on_cancel_all = ['Sales Invoice'];
		this.setup_queries();
	}

	onload() {
		if (this.frm.is_new()) {
			this.calculate_totals();
		}
	}

	refresh() {
		erpnext.hide_company();
		erpnext.toggle_naming_series();
		this.setup_buttons();
		this.update_dynamic_fields();
	}

	setup_queries() {
		let me = this;

		me.frm.set_query("employee", function() {
			return {
				filters: {
					status: 'Active',
				}
			}
		});

		me.frm.set_query("task", "time_logs", function(frm, cdt, cdn) {
			let row = frappe.get_doc(cdt, cdn);

			let filters = {status: ['!=', 'Cancelled']}
			if (row.project) {
				filters.project = row.project;
			}

			return {
				filters: filters
			}
		});

		me.frm.set_query("project", "time_logs", function() {
			let filters = {company: me.frm.doc.company}
			if (me.frm.doc.customer) {
				filters.customer = me.frm.doc.customer;
			}

			return {
				filters: filters
			}
		});
	}

	setup_buttons() {
		let me = this;
		if (me.frm.doc.docstatus == 1) {
			if (me.frm.doc.total_billable_hours && me.frm.doc.total_billable_hours > me.frm.doc.total_billed_hours) {
				me.frm.add_custom_button(__('Create Sales Invoice'), () => me.make_invoice());
			}
		}

		if (!me.frm.is_new() && me.frm.doc.docstatus == 0) {
			let button = (me.frm.doc.time_logs || []).some(
				d => d.from_time <= frappe.datetime.now_datetime() && !d.completed
			) ? 'Resume Timer' : 'Start Timer';

			me.frm.add_custom_button(__(button), () => me.setup_timer()).addClass("btn-primary");
		}
	}

	setup_timer() {
		let me = this;
		let flag = true;
		$.each(me.frm.doc.time_logs || [], function(i, row) {
			// Fetch the row for which from_time is not present
			if (flag && row.activity_type && !row.from_time){
				erpnext.timesheet.timer(me.frm, row);
				row.from_time = frappe.datetime.now_datetime();
				me.frm.refresh_fields("time_logs");
				me.frm.save();
				flag = false;
			}
			// Fetch the row for timer where activity is not completed and from_time is before now_time
			if (flag && row.from_time <= frappe.datetime.now_datetime() && !row.completed) {
				let timestamp = moment(frappe.datetime.now_datetime()).diff(moment(row.from_time),"seconds");
				erpnext.timesheet.timer(me.frm, row, timestamp);
				flag = false;
			}
		});
		// If no activities found to start a timer, create new
		if (flag) {
			erpnext.timesheet.timer(me.frm);
		}
	}

	update_dynamic_fields() {
		this.frm.fields_dict.time_logs.grid.toggle_enable("billing_hours", flt(this.frm.doc.per_billed) == 0);
		this.frm.fields_dict.time_logs.grid.toggle_enable("billable", flt(this.frm.doc.per_billed) == 0);
	}

	time_logs_add() {
		this.calculate_totals();
	}

	time_logs_remove() {
		this.calculate_totals();
	}

	activity_type(doc, cdt, cdn) {
		let me = this;
		let row = frappe.get_doc(cdt, cdn);
		frappe.call({
			method: "erpnext.projects.doctype.timesheet.timesheet.get_activity_cost",
			args: {
				employee: me.frm.doc.employee,
				activity_type: row.activity_type
			},
			callback: function(r){
				if(r.message){
					frappe.model.set_value(cdt, cdn, 'billing_rate', r.message['billing_rate']);
					frappe.model.set_value(cdt, cdn, 'costing_rate', r.message['costing_rate']);
					me.calculate_totals();
				}
			}
		});
	}

	task(doc, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);
		frappe.db.get_value("Task", row.task, "project", (r) => {
			frappe.model.set_value(cdt, cdn, "project", r.project);
		});
	}

	from_time(doc, cdt, cdn) {
		this.calculate_end_time(cdt, cdn);
	}

	hours(doc, cdt, cdn) {
		this.calculate_end_time(cdt, cdn);
	}

	to_time(doc, cdt, cdn) {
		if (this.frm._setting_hours) return;

		let row = frappe.get_doc(cdt, cdn);
		let hours = moment(row.to_time).diff(moment(row.from_time), "seconds") / 3600;
		frappe.model.set_value(cdt, cdn, "hours", hours);
	}

	billable() {
		this.calculate_totals();
	}

	billing_hours() {
		this.calculate_totals();
	}

	billing_rate() {
		this.calculate_totals();
	}

	costing_rate() {
		this.calculate_totals();
	}

	calculate_totals() {
		this.frm.doc.total_hours = 0;
		this.frm.doc.total_costing_amount = 0;
		this.frm.doc.total_billable_hours = 0;
		this.frm.doc.total_billable_amount = 0;

		this.frm.doc.time_logs.forEach(d => {
			frappe.model.round_floats_in(d);

			d.costing_amount = flt(d.costing_rate * d.hours);

			this.frm.doc.total_hours += d.hours;
			this.frm.doc.total_costing_amount += d.costing_amount;

			if (d.billable) {
				d.billing_hours = d.hours;
				d.billing_amount = flt(d.billing_rate * d.billing_hours);

				this.frm.doc.total_billable_hours += d.billing_hours;
				this.frm.doc.total_billable_amount += d.billing_amount;
			} else {
				d.billing_hours = 0.0;
				d.billing_rate = 0.0;
			}
		})
		this.frm.debounced_refresh_fields();
	}

	calculate_end_time(cdt, cdn) {
		let me = this;
		let row = frappe.get_doc(cdt, cdn);

		if(!row.from_time) {
			frappe.model.set_value(cdt, cdn, "from_time", frappe.datetime.get_datetime_as_string());
		}

		let d = moment(row.from_time);
		if(row.hours) {
			d.add(row.hours, "hours");
			me.frm._setting_hours = true;
			frappe.model.set_value(cdt, cdn, "to_time", d.format(frappe.defaultDatetimeFormat)).then(() => {
				me.frm._setting_hours = false;
				me.calculate_totals();
			});
		}
	}

	make_invoice() {
		let me = this;

		let fields = [{
			"fieldtype": "Link",
			"label": __("Item Code"),
			"fieldname": "item_code",
			"options": "Item"
		}];

		if (!me.frm.doc.customer) {
			fields.push({
				"fieldtype": "Link",
				"label": __("Customer"),
				"fieldname": "customer",
				"options": "Customer"
			});
		}

		let dialog = new frappe.ui.Dialog({
			title: __("Create Sales Invoice"),
			fields: fields,
			primary_action: function() {
				let data = dialog.get_values();
				frappe.call({
					method: "erpnext.projects.doctype.timesheet.timesheet.make_sales_invoice",
					args: {
						"source_name": me.frm.doc.name,
						"item_code": data.item_code,
						"customer": data.customer || me.frm.doc.customer
					},
					freeze: true,
					callback: function(r) {
						if(!r.exc) {
							frappe.model.sync(r.message);
							frappe.set_route("Form", r.message.doctype, r.message.name);
						}
					}
				});
				dialog.hide();
			}
		});
		dialog.show();
	}

	make_salary_slip() {
		frappe.model.open_mapped_doc({
			method: "erpnext.projects.doctype.timesheet.timesheet.make_salary_slip",
			frm: this.frm
		});
	}
}

extend_cscript(cur_frm.cscript, new erpnext.projects.Timesheet({frm: cur_frm}));
