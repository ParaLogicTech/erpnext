// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.provide("erpnext.manufacturing");

erpnext.manufacturing.JobCard = class JobCard extends frappe.ui.form.Controller {
	setup() {
		this.setup_queries();
	}

	refresh() {
		erpnext.hide_company();

		frappe.flags.pause_job = 0;
		frappe.flags.resume_job = 0;

		this.setup_buttons();
	}

	validate() {
		if ((!this.frm.doc.time_logs || !this.frm.doc.time_logs.length) && this.frm.doc.started_time) {
			this.reset_timer();
		}
	}

	setup_queries() {
		this.frm.set_query("work_order", () => {
			return {
				filters: {docstatus: 1}
			};
		});

		this.frm.set_query("operation", () => {
			return {
				query: "erpnext.manufacturing.doctype.job_card.job_card.get_operations",
				filters: {
					"work_order": this.frm.doc.work_order
				}
			};
		});

		this.frm.set_query("workstation", () => {
			return erpnext.queries.workstation(this.frm.doc.operation);
		});
	}

	setup_buttons() {
		if(!this.frm.doc.__islocal && this.frm.doc.items && this.frm.doc.items.length) {
			if (
				this.frm.doc.material_transfer_required
				&& flt(this.frm.doc.transferred_qty) < flt(this.frm.doc.for_quantity)
			) {
				this.frm.add_custom_button(__("Material Request"), () => {
					this.make_material_request();
				});

				this.frm.add_custom_button(__("Material Transfer"), () => {
					this.make_material_transfer();
				}).addClass("btn-primary");
			}
		}

		this.toggle_operation_number();

		if (
			!this.frm.is_new()
			&& this.frm.doc.docstatus == 0
			&& !cint(frappe.defaults.get_default("disable_capacity_planning"))
			&& (this.frm.doc.total_completed_qty < this.frm.doc.for_quantity || !this.frm.doc.for_quantity)
		) {
			if (this.frm.doc.work_order) {
				frappe.db.get_value('Work Order', this.frm.doc.work_order, ['skip_transfer', 'status'], (result) => {
					if (result.skip_transfer === 1 || result.status == 'In Process' || this.frm.doc.transferred_qty > 0 || !this.frm.doc.items.length) {
						this.prepare_timer_buttons();
					}
				});
			} else {
				this.prepare_timer_buttons();
			}
		}
	}

	work_order() {
		return frappe.run_serially([
			() => this.get_work_order_details(),
			() => this.frm.set_value("operation", null),
			() => this.frm.set_value("workstation", null),
		]);
	}

	get_work_order_details() {
		return this.frm.call({
			method: "erpnext.manufacturing.doctype.job_card.job_card.get_work_order_details",
			child: this.frm.doc,
			args: {
				"work_order": this.frm.doc.work_order,
				"operation": this.frm.doc.operation
			},
			callback: () => {
				this.frm.refresh_fields();
			}
		});
	}

	operation() {
		return frappe.run_serially([
			() => this.get_operation_id(),
			() => this.get_required_items(),
		]);
	}

	get_operation_id() {
		if (this.frm.doc.work_order && this.frm.doc.operation) {
			return frappe.call({
				method: "erpnext.manufacturing.doctype.job_card.job_card.get_operation_details",
				args: {
					"work_order": this.frm.doc.work_order,
					"operation": this.frm.doc.operation
				},
				callback: (r) => {
					if (r.message) {
						if (r.message.length == 1) {
							this.frm.set_value("operation_id", r.message[0].name);
						} else {
							this.frm.set_value("operation_id", null);

							let options = [];

							r.message.forEach((row) => {
								options.push({"label": row.idx, "value": row.name});
							});

							let description = __("Operation {0} added multiple times in the work order {1}",
								[this.frm.doc.operation, this.frm.doc.work_order]);

							this.frm.set_df_property("operation_row_number", "options", options);
							this.frm.set_df_property("operation_row_number", "description", description);
						}

						this.toggle_operation_number();
					}
				}
			})
		} else {
			this.frm.set_value("operation_id", null);
			this.toggle_operation_number();
		}
	}

	operation_row_number() {
		if (this.frm.doc.operation_row_number) {
			this.frm.set_value("operation_id", this.frm.doc.operation_row_number);
		}
	}

	toggle_operation_number() {
		this.frm.toggle_display("operation_row_number", !this.frm.doc.operation_id && this.frm.doc.operation);
		this.frm.toggle_reqd("operation_row_number", !this.frm.doc.operation_id && this.frm.doc.operation);
	}

	for_quantity() {
		return this.get_required_items();
	}

	get_required_items() {
		if (flt(this.frm.doc.for_quantity) > 0 && this.frm.doc.operation) {
			return this.frm.call({
				method: "set_required_items",
				doc: this.frm.doc,
				callback: () => {
					this.frm.refresh_field("items");
				}
			});
		} else {
			this.frm.clear_table("items");
			this.frm.refresh_field("items");
		}
	}

	employee() {
		if (this.frm.doc.job_started && !this.frm.doc.current_time) {
			this.reset_timer();
		} else {
			this.start_job();
		}
	}

	prepare_timer_buttons() {
		this.make_dashboard();
		if (!this.frm.doc.job_started) {
			this.frm.add_custom_button(__("Start"), () => {
				if (!this.frm.doc.employee) {
					frappe.prompt(
						{fieldtype: 'Link', label: __('Employee'), options: "Employee", fieldname: 'employee'},
						(d) => {
							if (d.employee) {
								this.frm.set_value("employee", d.employee);
							} else {
								this.start_job();
							}
						},
						__("Enter Value"),
						__("Start")
					);
				} else {
					this.start_job();
				}
			}).addClass("btn-primary");
		} else if (this.frm.doc.status == "On Hold") {
			this.frm.add_custom_button(__("Resume"), () => {
				frappe.flags.resume_job = 1;
				this.start_job();
			}).addClass("btn-primary");
		} else {
			this.frm.add_custom_button(__("Pause"), () => {
				frappe.flags.pause_job = 1;
				this.frm.set_value("status", "On Hold");
				this.complete_job();
			});

			this.frm.add_custom_button(__("Complete"), () => {
				let completed_time = frappe.datetime.now_datetime();
				this.hide_timer();

				if (this.frm.doc.for_quantity) {
					frappe.prompt({fieldtype: 'Float', label: __('Completed Quantity'),
						fieldname: 'qty', reqd: 1, default: this.frm.doc.for_quantity}, data => {
							this.complete_job(completed_time, data.qty);
						}, __("Enter Value"), __("Complete"));
				} else {
					this.complete_job(completed_time, 0);
				}
			}).addClass("btn-primary");
		}
	}

	start_job() {
		let row = frappe.model.add_child(this.frm.doc, 'Job Card Time Log', 'time_logs');
		row.from_time = frappe.datetime.now_datetime();
		this.frm.set_value('job_started', 1);
		this.frm.set_value('started_time' , row.from_time);
		this.frm.set_value("status", "Work In Progress");

		if (!frappe.flags.resume_job) {
			this.frm.set_value('current_time' , 0);
		}

		this.frm.save();
	}

	complete_job(completed_time, completed_qty) {
		this.frm.doc.time_logs.forEach(d => {
			if (d.from_time && !d.to_time) {
				d.to_time = completed_time || frappe.datetime.now_datetime();
				d.completed_qty = completed_qty || 0;

				if(frappe.flags.pause_job) {
					let currentIncrement = moment(d.to_time).diff(moment(d.from_time),"seconds") || 0;
					this.frm.set_value('current_time' , currentIncrement + (this.frm.doc.current_time || 0));
				} else {
					this.frm.set_value('started_time' , '');
					this.frm.set_value('job_started', 0);
					this.frm.set_value('current_time' , 0);
				}

				this.frm.save();
			}
		});
	}

	reset_timer() {
		this.frm.set_value('started_time' , '');
		this.frm.set_value('job_started', 0);
		this.frm.set_value('current_time' , 0);
	}

	make_dashboard() {
		if(this.frm.doc.__islocal) {
			return;
		}

		this.frm.dashboard.refresh();
		const timer = `
			<div class="stopwatch" style="font-weight:bold;margin:0px 13px 0px 2px;
				color:#545454;font-size:18px;display:inline-block;vertical-align:text-bottom;>
				<span class="hours">00</span>
				<span class="colon">:</span>
				<span class="minutes">00</span>
				<span class="colon">:</span>
				<span class="seconds">00</span>
			</div>`;

		let section = this.frm.toolbar.page.add_inner_message(timer);

		let currentIncrement = this.frm.doc.current_time || 0;
		if (this.frm.doc.started_time || this.frm.doc.current_time) {
			if (this.frm.doc.status == "On Hold") {
				updateStopwatch(currentIncrement);
			} else {
				currentIncrement += moment(frappe.datetime.now_datetime()).diff(moment(this.frm.doc.started_time), "seconds");
				initialiseTimer();
			}

			function initialiseTimer() {
				const interval = setInterval(function() {
					var current = setCurrentIncrement();
					updateStopwatch(current);
				}, 1000);
			}

			function updateStopwatch(increment) {
				var hours = Math.floor(increment / 3600);
				var minutes = Math.floor((increment - (hours * 3600)) / 60);
				var seconds = increment - (hours * 3600) - (minutes * 60);

				$(section).find(".hours").text(hours < 10 ? ("0" + hours.toString()) : hours.toString());
				$(section).find(".minutes").text(minutes < 10 ? ("0" + minutes.toString()) : minutes.toString());
				$(section).find(".seconds").text(seconds < 10 ? ("0" + seconds.toString()) : seconds.toString());
			}

			function setCurrentIncrement() {
				currentIncrement += 1;
				return currentIncrement;
			}
		}
	}

	hide_timer() {
		this.frm.toolbar.page.inner_toolbar.find(".stopwatch").remove();
	}

	completed_qty() {
		this.set_total_completed_qty();
	}

	to_time() {
		this.frm.set_value('job_started', 0);
		this.frm.set_value('started_time', '');
	}

	set_total_completed_qty() {
		this.frm.doc.total_completed_qty = 0;
		this.frm.doc.time_logs.forEach(d => {
			if (d.completed_qty) {
				this.frm.doc.total_completed_qty += d.completed_qty;
			}
		});

		this.frm.refresh_field("total_completed_qty");
	}

	make_material_request() {
		frappe.model.open_mapped_doc({
			method: "erpnext.manufacturing.doctype.job_card.job_card.make_material_request",
			frm: this.frm,
			run_link_triggers: true
		});
	}

	make_material_transfer() {
		frappe.model.open_mapped_doc({
			method: "erpnext.manufacturing.doctype.job_card.job_card.make_material_transfer",
			frm: this.frm,
			run_link_triggers: true
		});
	}
}

extend_cscript(cur_frm.cscript, new erpnext.manufacturing.JobCard({frm: cur_frm}));
