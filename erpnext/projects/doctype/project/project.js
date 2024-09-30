// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide('erpnext.projects');

{% include 'erpnext/vehicles/vehicle_checklist.js' %};
{% include 'erpnext/vehicles/customer_vehicle_selector.js' %};

erpnext.projects.ProjectController = class ProjectController extends crm.QuickContacts {
	setup() {
		this.setup_make_methods();
		erpnext.setup_applies_to_fields(this.frm);
	}

	onload() {
		super.onload();
		this.setup_queries();
	}

	refresh() {
		erpnext.hide_company();
		this.set_dynamic_link();
		this.setup_route_options();
		this.setup_naming_series();
		this.setup_web_link();
		this.setup_buttons();
		this.set_status_read_only();
		this.set_percent_complete_read_only();
		this.set_cant_change_read_only();
		this.toggle_vehicle_odometer_fields();
		this.make_vehicle_checklist();
		this.make_customer_request_checklist();
		this.make_customer_vehicle_selector();
		this.make_document_checklist();
		this.set_sales_data_html();
		this.set_service_advisor_from_user();
		this.setup_vehicle_panel_fields();
		this.setup_dashboard();
	}

	setup_queries() {
		var me = this;

		me.frm.set_query('customer', 'erpnext.controllers.queries.customer_query');
		me.frm.set_query('bill_to', 'erpnext.controllers.queries.customer_query');
		if (me.frm.fields_dict.vehicle_owner) {
			me.frm.set_query('vehicle_owner', 'erpnext.controllers.queries.customer_query');
		}

		me.frm.set_query('contact_person', erpnext.queries.contact_query);
		me.frm.set_query('secondary_contact_person', erpnext.queries.contact_query);
		me.frm.set_query('customer_address', erpnext.queries.address_query);

		if (me.frm.fields_dict.insurance_company) {
			me.frm.set_query("insurance_company", function(doc) {
				return {
					query: "erpnext.controllers.queries.customer_query",
					filters: {is_insurance_company: 1}
				};
			});
		}

		// sales order
		me.frm.set_query('sales_order', function () {
			var filters = {
				'project': ["in", me.frm.doc.__islocal ? [""] : [me.frm.doc.name, ""]]
			};

			if (me.frm.doc.customer) {
				filters["customer"] = me.frm.doc.customer;
			}

			return {
				filters: filters
			};
		});

		// depreciation item
		me.frm.set_query('depreciation_item_code', 'non_standard_depreciation', () => erpnext.queries.item());
		me.frm.set_query('underinsurance_item_code', 'non_standard_underinsurance', () => erpnext.queries.item());

		me.frm.set_query("project_template", "project_templates",
			() => erpnext.queries.project_template(me.frm.doc.applies_to_item));
	}

	set_dynamic_link() {
		frappe.dynamic_link = {doc: this.frm.doc, fieldname: 'customer', doctype: 'Customer'};
	}

	setup_route_options() {
		var me = this;

		var sales_order_field = me.frm.get_docfield("sales_order");
		if (sales_order_field) {
			sales_order_field.get_route_options_for_new_doc = function (field) {
				if (me.frm.is_new()) return;
				return {
					"customer": me.frm.doc.customer,
					"project": me.frm.doc.name
				};
			};
		}
	}

	setup_naming_series() {
		if (frappe.defaults.get_default("project_naming_by")!="Naming Series") {
			this.frm.toggle_display("naming_series", false);
		} else {
			erpnext.toggle_naming_series();
		}
	}

	setup_web_link() {
		if (this.frm.doc.__islocal) {
			this.frm.web_link && this.frm.web_link.remove();
		} else {
			this.frm.add_web_link("/projects?project=" + encodeURIComponent(this.frm.doc.name));
			this.frm.trigger('show_dashboard');
		}
	}

	setup_make_methods() {
		var me = this;

		me.frm.custom_make_buttons = {
			'Sales Invoice': 'Sales Invoice',
			'Delivery Note': 'Delivery Note',
			'Vehicle Service Receipt': 'Receive Vehicle',
			'Vehicle Gate Pass': 'Create Delivery Gate Pass',
			'Vehicle Log': 'Update Odometer',
		};

		var make_method_doctypes = [
			'Maintenance Visit', 'Warranty Claim', 'Quality Inspection', 'Timesheet',
		];

		me.frm.make_methods = {};
		$.each(make_method_doctypes, function (i, dt) {
			me.frm.make_methods[dt] = () => me.open_form(dt);
		});
	}

	setup_buttons() {
		var me = this;

		if (me.frm.doc.status == "Open") {
			me.frm.add_custom_button(__('Select Appointment'), () => {
				me.select_appointment();
			});
		}

		if (!me.frm.is_new()) {
			// Set Status
			if (!me.frm.doc.ready_to_close && !['Cancelled', 'Closed'].includes(me.frm.doc.status)) {
				me.frm.add_custom_button(__('Ready To Close'), () => {
					me.set_project_ready_to_close();
				}, __('Set Status'));
			}

			if (me.frm.doc.status != 'Open' || (me.frm.doc.__onload && me.frm.doc.__onload.is_manual_project_status)) {
				me.frm.add_custom_button(__('Re-Open'), () => {
					me.reopen_project(false);
				}, __('Set Status'));
			}

			if (me.frm.doc.__onload && me.frm.doc.__onload.valid_manual_project_status_names) {
				$.each(me.frm.doc.__onload.valid_manual_project_status_names || [], function (i, project_status) {
					if (me.frm.doc.project_status != project_status) {
						me.frm.add_custom_button(__(project_status), () => {
							me.set_project_status(project_status);
						}, __('Set Status'));
					}
				});
			}

			// Task Buttons
			if (frappe.model.can_read("Task")) {
				me.frm.add_custom_button(__("Gantt Chart"), function () {
					frappe.route_options = {
						"project": me.frm.doc.name
					};
					frappe.set_route("List", "Task", "Gantt");
				}, __("Tasks"));

				me.frm.add_custom_button(__("Kanban Board"), () => {
					frappe.call('erpnext.projects.doctype.project.project.create_kanban_board_if_not_exists', {
						project: me.frm.doc.name
					}).then(() => {
						frappe.set_route('List', 'Task', 'Kanban', me.frm.doc.name);
					});
				}, __("Tasks"));
			}

			me.frm.add_custom_button(__('Duplicate Project with Tasks'), () => me.create_duplicate(), __("Tasks"));

			// Vehicle Buttons
			if (me.frm.doc.applies_to_vehicle) {
				if (frappe.model.can_create("Vehicle Service Receipt") && me.frm.doc.vehicle_status == "Not Received") {
					me.frm.add_custom_button(__("Receive Vehicle"), () => me.make_vehicle_receipt(), __("Vehicle"));
				}

				if (frappe.model.can_create("Vehicle Gate Pass") && me.frm.doc.vehicle_status == "In Workshop") {
					if (cint(me.frm.doc.ready_to_close)) {
						me.frm.add_custom_button(__("Create Delivery Gate Pass"),
							() => me.make_vehicle_gate_pass("Service - Vehicle Delivery"), __("Vehicle"));
					}

					me.frm.add_custom_button(__("Create Test Drive Gate Pass"),
						() => me.make_vehicle_gate_pass("Service - Test Drive"), __("Tasks"));
				}

				if (frappe.model.can_create("Vehicle Log")) {
					me.frm.add_custom_button(__("Update Odometer"), () => me.make_odometer_log(), __("Vehicle"));
				}

				if (frappe.model.can_write("Project")) {
					me.frm.add_custom_button(__("Reload Vehicle Details"), () => me.reload_vehicle_details(), __("Vehicle"));
				}
			}

			// Create Buttons
			if (frappe.model.can_create("Sales Invoice")) {
				me.frm.add_custom_button(__("Sales Invoice"), () => me.make_sales_invoice(), __("Create"));
			}

			if (frappe.model.can_create("Delivery Note")) {
				me.frm.add_custom_button(__("Delivery Note"), () => me.make_delivery_note(), __("Create"));
			}

			if (frappe.model.can_create("Sales Order")) {
				me.frm.add_custom_button(__("Sales Order (Services)"), () => me.make_sales_order("service"), __("Create"));
				me.frm.add_custom_button(__("Sales Order (Materials)"), () => me.make_sales_order("stock"), __("Create"));
				me.frm.add_custom_button(__("Sales Order (All)"), () => me.make_sales_order(), __("Create"));
			}
		}
	}

	setup_dashboard() {
		if (this.frm.doc.__islocal) {
			return;
		}

		var me = this;
		var company_currency = erpnext.get_currency(me.frm.doc.company);

		me.frm.dashboard.stats_area_row.empty();
		me.frm.dashboard.stats_area.show();

		// Work Status
		var vehicle_status_color;
		if (me.frm.doc.vehicle_status == "Not Applicable") {
			vehicle_status_color = "light-gray";
		} else if (me.frm.doc.vehicle_status == "Not Received") {
			vehicle_status_color = "red";
		} else if (me.frm.doc.vehicle_status == "In Workshop") {
			vehicle_status_color = "yellow";
		} else if (me.frm.doc.vehicle_status == "Delivered") {
			vehicle_status_color = "green";
		}

		var tasks_status_color;
		if (me.frm.doc.tasks_status == "No Tasks") {
			tasks_status_color = "light-gray";
		} else if (me.frm.doc.tasks_status == "Not Started") {
			tasks_status_color = "orange";
		} else if (me.frm.doc.tasks_status == "In Progress") {
			tasks_status_color = "yellow";
		} else if (me.frm.doc.tasks_status == "On Hold") {
			tasks_status_color = "red";
		} else if (me.frm.doc.tasks_status == "Completed") {
			tasks_status_color = "green";
		}

		var task_count = "";
		if (me.frm.doc.__onload?.task_count && me.frm.doc.__onload.task_count.total_tasks) {
			task_count = ` (${me.frm.doc.__onload.task_count.completed_tasks}/${me.frm.doc.__onload.task_count.total_tasks})`;
		}

		var delivery_status_color;
		if (me.frm.doc.delivery_status == "Not Applicable") {
			delivery_status_color = "light-gray";
		} else if (me.frm.doc.delivery_status == "Not Delivered") {
			delivery_status_color = "orange";
		} else if (me.frm.doc.delivery_status == "Partly Delivered") {
			delivery_status_color = "yellow";
		} else if (me.frm.doc.delivery_status == "Fully Delivered") {
			delivery_status_color = "green";
		}

		var status_items = [
			{
				contents: __('Tasks Status: {0}{1}', [me.frm.doc.tasks_status, task_count]),
				indicator: tasks_status_color
			},
			{
				contents: __('Material Status: {0}', [me.frm.doc.delivery_status]),
				indicator: delivery_status_color
			},
			{
				contents: __('Ready To Close: {0}', [me.frm.doc.ready_to_close ? __("Yes") : __("No")]),
				indicator: me.frm.doc.ready_to_close ? 'green' : 'orange'
			},
		];

		if (me.frm.get_field('vehicle_status')) {
			var vehicle_status_item = {
				contents: __('Vehicle Status: {0}', [me.frm.doc.vehicle_status]),
				indicator: vehicle_status_color
			};
			status_items = [vehicle_status_item].concat(status_items);
		}

		me.add_indicator_section(__("Status"), status_items);

		// Billing Status
		var billing_status_color;
		if (me.frm.doc.billing_status == "Not Applicable") {
			billing_status_color = "light-gray";
		} else if (me.frm.doc.billing_status == "Not Billed") {
			billing_status_color = "orange";
		} else if (me.frm.doc.billing_status == "Partly Billed") {
			billing_status_color = "yellow";
		} else if (me.frm.doc.billing_status == "Fully Billed") {
			billing_status_color = "green";
		}

		var total_billable_color = me.frm.doc.total_billable_amount ? "blue" : "light-gray";
		var customer_billable_color = me.frm.doc.customer_billable_amount ? "blue" : "light-gray";

		var billed_amount_color;
		if (me.frm.doc.total_billed_amount) {
			if (me.frm.doc.total_billed_amount < me.frm.doc.total_billable_amount) {
				billed_amount_color = 'yellow';
			} else if (me.frm.doc.total_billed_amount > me.frm.doc.total_billable_amount) {
				billed_amount_color = 'purple';
			} else {
				billed_amount_color = 'green';
			}
		} else {
			if (me.frm.doc.total_billable_amount) {
				billed_amount_color = 'orange';
			} else {
				billed_amount_color = 'light-gray';
			}
		}

		var billing_items = [
			{
				contents: __('Billing Status: {0}', [me.frm.doc.billing_status]),
				indicator: billing_status_color
			},
		]

		if (me.frm.fields_dict.total_billable_amount && me.frm.fields_dict.total_billable_amount.disp_status != "None") {
			billing_items.push({
				contents: __('Total Billable: {0}', [format_currency(me.frm.doc.total_billable_amount, company_currency)]),
				indicator: total_billable_color
			});
		}


		if (me.frm.fields_dict.customer_billable_amount && me.frm.fields_dict.customer_billable_amount.disp_status != "None") {
			billing_items.push({
				contents: __('Customer Billable: {0}', [format_currency(me.frm.doc.customer_billable_amount, company_currency)]),
				indicator: customer_billable_color
			});
		}

		if (me.frm.fields_dict.total_billed_amount && me.frm.fields_dict.total_billed_amount.disp_status != "None") {
			billing_items.push({
				contents: __('Billed Amount: {0}', [format_currency(me.frm.doc.total_billed_amount, company_currency)]),
				indicator: billed_amount_color
			});
		}

		me.add_indicator_section(__("Billing"), billing_items);
	}

	add_indicator_section(title, items) {
		var items_html = '';
		$.each(items || [], function (i, d) {
			items_html += `<span class="indicator ${d.indicator}">${d.contents}</span>`
		});

		var html = $(`<div class="flex-column col-sm-4 col-md-4">
			<div><h5>${title}</h5></div>
			${items_html}
		</div>`);

		html.appendTo(this.frm.dashboard.stats_area_row);

		return html
	}

	toggle_vehicle_odometer_fields() {
		if (this.frm.fields_dict.vehicle_first_odometer && this.frm.fields_dict.vehicle_last_odometer) {
			var first_odometer_read_only = cint(this.frm.doc.vehicle_first_odometer);

			if (!this.frm.doc.applies_to_vehicle || this.frm.doc.__islocal) {
				first_odometer_read_only = 0;
			}

			this.frm.set_df_property("vehicle_first_odometer", "read_only", first_odometer_read_only);
		}
	}

	set_cant_change_read_only() {
		const cant_change_fields = (this.frm.doc.__onload && this.frm.doc.__onload.cant_change_fields) || {};
		$.each(cant_change_fields, (fieldname, cant_change) => {
			this.frm.set_df_property(fieldname, 'read_only', cant_change ? 1 : 0);
		});
	}

	create_duplicate() {
		var me = this;
		return new Promise(resolve => {
			frappe.prompt('Project Name', (data) => {
				frappe.xcall('erpnext.projects.doctype.project.project.create_duplicate_project',
					{
						prev_doc: me.frm.doc,
						project_name: data.value
					}).then(() => {
					frappe.set_route('Form', "Project", data.value);
					frappe.show_alert(__("Duplicate project has been created"));
				});
				resolve();
			});
		});
	}

	set_project_status(project_status) {
		var me = this;

		me.frm.check_if_unsaved();
		frappe.confirm(__('Set status as <b>{0}</b>?', [project_status]), () => {
			frappe.xcall('erpnext.projects.doctype.project.project.set_project_status',
				{project: me.frm.doc.name, project_status: project_status}).then(() => me.frm.reload_doc());
		});
	}

	set_project_ready_to_close() {
		var me = this;

		me.frm.check_if_unsaved();
		frappe.confirm(__('Are you sure you want to mark this Project as <b>Ready To Close</b>?'), () => {
			frappe.xcall('erpnext.projects.doctype.project.project.set_project_ready_to_close',
				{project: me.frm.doc.name}).then(() => me.frm.reload_doc());
		});
	}

	reopen_project() {
		var me = this;

		me.frm.check_if_unsaved();
		frappe.confirm(__('Are you sure you want to <b>Re-Open</b> this Project?'), () => {
			frappe.xcall('erpnext.projects.doctype.project.project.reopen_project_status',
				{project: me.frm.doc.name}).then(() => me.frm.reload_doc());
		});
	}

	customer() {
		this.get_customer_details();
		this.reload_customer_vehicle_selector();
	}

	get_customer_details() {
		var me = this;

		return frappe.call({
			method: "erpnext.projects.doctype.project.project.get_customer_details",
			args: {
				args: {
					doctype: me.frm.doc.doctype,
					company: me.frm.doc.company,
					customer: me.frm.doc.customer,
					bill_to: me.frm.doc.bill_to,
				}
			},
			callback: function (r) {
				if (r.message && !r.exc) {
					frappe.run_serially([
						() => me.frm.set_value(r.message),
						() => me.setup_contact_no_fields(r.message.contact_nos),
					]);
				}
			}
		});
	}

	customer_address() {
		erpnext.utils.get_address_display(this.frm, "customer_address");
	}

	applies_to_vehicle() {
		this.reload_customer_vehicle_selector();
	}
	vehicle_owner() {
		if (!this.frm.doc.vehicle_owner) {
			this.frm.doc.vehicle_owner_name = null;
		}
	}

	vehicle_chassis_no() {
		erpnext.utils.format_vehicle_id(this.frm, 'vehicle_chassis_no');
	}
	vehicle_engine_no() {
		erpnext.utils.format_vehicle_id(this.frm, 'vehicle_engine_no');
	}
	vehicle_license_plate() {
		erpnext.utils.format_vehicle_id(this.frm, 'vehicle_license_plate');
	}

	project_template(doc, cdt, cdn) {
		var row = frappe.get_doc(cdt, cdn);
		this.get_project_template_details(row);
	}

	get_project_template_details(row) {
		var me = this;

		if (row && row.project_template) {
			frappe.call({
				method: "erpnext.projects.doctype.project_template.project_template.get_project_template_details",
				args: {
					project_template: row.project_template
				},
				callback: function (r) {
					if (r.message) {
						var customer_request_checklist = r.message.customer_request_checklist;
						delete r.message['customer_request_checklist'];

						frappe.model.set_value(row.doctype, row.name, r.message);

						if (customer_request_checklist && customer_request_checklist.length && me.frm.get_field('customer_request_checklist')) {
							$.each(me.frm.doc.customer_request_checklist || [], function (i, d) {
								if (d.checklist_item && customer_request_checklist.includes(d.checklist_item)) {
									d.checklist_item_checked = 1;
								}
							});

							me.refresh_customer_request_checklist();
						}
					}
				}
			});
		}
	}

	make_vehicle_checklist() {
		if (this.frm.fields_dict.vehicle_checklist_html) {
			var is_read_only = cint(this.frm.doc.__onload && this.frm.doc.__onload.cant_change_fields && this.frm.doc.__onload.cant_change_fields.vehicle_checklist);

			this.frm.vehicle_checklist_editor = erpnext.vehicles.make_vehicle_checklist(this.frm,
				'vehicle_checklist',
				this.frm.fields_dict.vehicle_checklist_html.wrapper,
				this.frm.doc.__onload && this.frm.doc.__onload.default_vehicle_checklist_items,
				is_read_only,
				__("Vehicle Checklist"));
		}
	}

	make_customer_request_checklist() {
		if (this.frm.fields_dict.customer_request_checklist_html) {
			var is_read_only = cint(this.frm.doc.__onload && this.frm.doc.__onload.cant_change_fields && this.frm.doc.__onload.cant_change_fields.customer_request_checklist);

			this.frm.customer_request_checklist_editor = erpnext.vehicles.make_vehicle_checklist(this.frm,
				'customer_request_checklist',
				this.frm.fields_dict.customer_request_checklist_html.wrapper,
				this.frm.doc.__onload && this.frm.doc.__onload.default_customer_request_checklist_items,
				is_read_only,
				__("Customer Request Checklist"));
		}
	}

	make_document_checklist() {
		if (this.frm.fields_dict.document_checklist_html) {
			var is_read_only = cint(this.frm.doc.__onload && this.frm.doc.__onload.cant_change_fields && this.frm.doc.__onload.cant_change_fields.document_checklist);

			this.frm.document_checklist_editor = erpnext.vehicles.make_vehicle_checklist(this.frm,
				'document_checklist',
				this.frm.fields_dict.document_checklist_html.wrapper,
				this.frm.doc.__onload && this.frm.doc.__onload.default_document_checklist_items,
				is_read_only,
				__("Document Checklist"));
		}
	}

	refresh_customer_request_checklist() {
		if (this.frm.customer_request_checklist_editor) {
			this.frm.customer_request_checklist_editor.refresh();
		}
	}

	render_document_checklist() {
		if (this.frm.document_checklist_editor) {
			this.frm.document_checklist_editor.render_checklist();
		}
	}

	make_customer_vehicle_selector() {
		if (this.frm.fields_dict.customer_vehicle_selector_html) {
			this.frm.customer_vehicle_selector = erpnext.vehicles.make_customer_vehicle_selector(this.frm,
				this.frm.fields_dict.customer_vehicle_selector_html.wrapper,
				'applies_to_vehicle',
				'customer',
			);
		}
	}

	reload_customer_vehicle_selector() {
		if (this.frm.customer_vehicle_selector) {
			this.frm.customer_vehicle_selector.load_and_render();
		}
	}

	set_sales_data_html() {
		this.frm.get_field("stock_items_html").$wrapper.html(this.frm.doc.__onload && this.frm.doc.__onload.stock_items_html || '');
		this.frm.get_field("service_items_html").$wrapper.html(this.frm.doc.__onload && this.frm.doc.__onload.service_items_html || '');
		this.frm.get_field("sales_summary_html").$wrapper.html(this.frm.doc.__onload && this.frm.doc.__onload.sales_summary_html || '');
	}

	project_workshop() {
		this.get_project_workshop_details();
	}

	project_type() {
		this.get_project_type_defaults();
	}

	get_project_workshop_details() {
		var me = this;

		if (me.frm.doc.project_workshop) {
			return frappe.call({
				method: "erpnext.projects.doctype.project_workshop.project_workshop.get_project_workshop_details",
				args: {
					project_workshop: me.frm.doc.project_workshop,
					company: me.frm.doc.company,
				},
				callback: function (r) {
					if (!r.exc) {
						return frappe.run_serially([
							() => me.frm.set_value(r.message),
							() => me.render_document_checklist(),
						]);
					}
				}
			});
		}
	}

	get_project_type_defaults() {
		var me = this;

		if (me.frm.doc.project_type) {
			return frappe.call({
				method: "erpnext.projects.doctype.project_type.project_type.get_project_type_defaults",
				args: {
					project_type: me.frm.doc.project_type
				},
				callback: function (r) {
					if (!r.exc) {
						return me.frm.set_value(r.message);
					}
				}
			});
		}
	}

	set_service_advisor_from_user() {
		if (!this.frm.get_field('service_advisor') || this.frm.doc.service_advisor || !this.frm.doc.__islocal) {
			return;
		}

		crm.utils.get_sales_person_from_user(sales_person => {
			if (sales_person) {
				this.frm.set_value('service_advisor', sales_person);
			}
		});
	}

	select_appointment() {
		var me = this;
		var dialog = new frappe.ui.Dialog({
			title: __("Select Appointment"),
			fields: [
				{
					label: __("Appointment Date"),
					fieldname: "scheduled_date",
					fieldtype: "Date",
					default: me.frm.doc.project_date || frappe.datetime.get_today(),
				},
				{
					label: __("Appointment"),
					fieldname: "appointment",
					fieldtype: "Link",
					options: "Appointment",
					only_select: 1,
					get_query: () => {
						var filters = {
							'docstatus': 1,
							'status': ['!=', 'Rescheduled']
						};
						if (dialog.get_value('scheduled_date')) {
							filters['scheduled_date'] = dialog.get_value('scheduled_date');
						}
						if (dialog.get_value('customer')) {
							filters['appointment_for'] = "Customer";
							filters['party_name'] = dialog.get_value('customer');
						}
						return {
							filters: filters
						}
					},
				},
			]
		});

		dialog.set_primary_action(__("Select"), function () {
			var appointment = dialog.get_value('appointment');
			me.get_appointment_details(appointment).then(() => {
				dialog.hide();
			})
		});

		dialog.show();
	}

	get_appointment_details(appointment) {
		var me = this;

		if (appointment) {
			return frappe.call({
				method: "erpnext.overrides.appointment.appointment_hooks.get_project",
				args: {
					source_name: appointment,
					target_doc: me.frm.doc,
				},
				callback: function (r) {
					if (!r.exc) {
						frappe.model.sync(r.message);
						me.frm.dirty();
						me.get_all_contact_nos();
						me.reload_customer_vehicle_selector();
						me.frm.refresh_fields();
					}
				}
			});
		} else {
			me.frm.dirty();
			return me.frm.set_value({
				"appointment": null,
				"appointment_dt": null,
			});
		}
	}

	collect_progress() {
		this.frm.set_df_property("message", "reqd", this.frm.doc.collect_progress);
	}

	percent_complete() {
		this.set_percent_complete_read_only();
	}

	set_percent_complete_read_only() {
		var read_only = cint(this.frm.doc.percent_complete_method != "Manual");
		this.frm.set_df_property("percent_complete", "read_only", read_only);
	}

	set_status_read_only() {
		var read_only = this.frm.doc.project_status ? 1 : 0;
		this.frm.set_df_property("status", "read_only", read_only);
	}

	open_form(doctype) {
		var me = this;

		var item_table_fieldnames = {
			'Maintenance Visit': 'purposes',
			'Stock Entry': 'items',
			'Delivery Note': 'items',
			'Timesheet': 'time_logs',
		};

		var items_fieldname = item_table_fieldnames[doctype];

		frappe.new_doc(doctype, {
			customer: me.frm.doc.customer,
			party: me.frm.doc.customer,
			party_name: me.frm.doc.customer,
			quotation_to: 'Customer',
			party_type: 'Customer',
			project: me.frm.doc.name,
			item_code: me.frm.doc.item_code,
			serial_no: me.frm.doc.serial_no,
			item_serial_no: me.frm.doc.serial_no
		}).then(r => {
			if (items_fieldname) {
				cur_frm.doc[items_fieldname] = [];
				var child = cur_frm.add_child(items_fieldname, {
					project: me.frm.doc.name
				});
				cur_frm.refresh_field(items_fieldname);
			}
		});
	}

	make_sales_invoice() {
		var me = this;
		me.frm.check_if_unsaved();

		if (
			me.frm.doc.default_depreciation_percentage
			|| me.frm.doc.default_underinsurance_percentage
			|| (me.frm.doc.non_standard_depreciation || []).length
			|| (me.frm.doc.non_standard_underinsurance || []).length
		) {
			var html = `
<div class="text-center">
	<button type="button" class="btn btn-primary btn-bill-customer">${__("Bill Depreciation Amount Only to <b>Customer (User)</b>")}</button>
	<br/><br/>
	<button type="button" class="btn btn-primary btn-bill-insurance">${__("Bill After Depreciation Amount to <b>Insurance Company</b>")}</button>
</div>
`;

			var dialog = new frappe.ui.Dialog({
				title: __("Depreciation Invoice"),
				fields: [
					{fieldtype: "HTML", options: html}
				],
			});

			dialog.show();

			$('.btn-bill-customer', dialog.$wrapper).click(function () {
				dialog.hide();
				me._make_sales_invoice('Depreciation Amount Only');
			});
			$('.btn-bill-insurance', dialog.$wrapper).click(function () {
				dialog.hide();
				me._make_sales_invoice('After Depreciation Amount');
			});
		} else {
			me._make_sales_invoice();
		}
	}

	_make_sales_invoice(depreciation_type) {
		return frappe.call({
			method: "erpnext.projects.doctype.project.project.make_sales_invoice",
			args: {
				"project_name": this.frm.doc.name,
				"depreciation_type": depreciation_type,
			},
			callback: function (r) {
				if (!r.exc) {
					var doclist = frappe.model.sync(r.message);
					frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				}
			}
		});
	}

	make_delivery_note() {
		var me = this;
		me.frm.check_if_unsaved();
		return frappe.call({
			method: "erpnext.projects.doctype.project.project.get_delivery_note",
			args: {
				"project_name": me.frm.doc.name,
			},
			callback: function (r) {
				if (!r.exc) {
					var doclist = frappe.model.sync(r.message);
					frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				}
			}
		});
	}

	make_sales_order(items_type) {
		var me = this;
		me.frm.check_if_unsaved();
		return frappe.call({
			method: "erpnext.projects.doctype.project.project.get_sales_order",
			args: {
				"project_name": me.frm.doc.name,
				"items_type": items_type,
			},
			callback: function (r) {
				if (!r.exc) {
					var doclist = frappe.model.sync(r.message);
					frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				}
			}
		});
	}

	make_vehicle_receipt() {
		this.frm.check_if_unsaved();
		return frappe.call({
			method: "erpnext.projects.doctype.project.project.get_vehicle_service_receipt",
			args: {
				"project": this.frm.doc.name
			},
			callback: function (r) {
				if (!r.exc) {
					var doclist = frappe.model.sync(r.message);
					frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				}
			}
		});
	}

	make_vehicle_gate_pass(purpose) {
		this.frm.check_if_unsaved();
		return frappe.call({
			method: "erpnext.projects.doctype.project.project.get_vehicle_gate_pass",
			args: {
				"project": this.frm.doc.name,
				"purpose": purpose,
			},
			callback: function (r) {
				if (!r.exc) {
					var doclist = frappe.model.sync(r.message);
					frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
				}
			}
		});
	}

	make_odometer_log() {
		var me = this;
		if (!me.frm.doc.applies_to_vehicle) {
			return;
		}

		var dialog = new frappe.ui.Dialog({
			title: __("Vehicle Odometer Log"),
			fields: [
				{"fieldtype": "Int", "label": __("New Odometer Reading"), "fieldname": "new_odometer", "reqd": 1},
				{"fieldtype": "Int", "label": __("Previous Odometer Reading"), "fieldname": "previous_odometer",
					"default": me.frm.doc.vehicle_last_odometer, "read_only": 1},
				{"fieldtype": "Date", "label": __("Reading Date"), "fieldname": "date", "default": "Today"},
			]
		});

		dialog.set_primary_action(__("Create"), function () {
			var values = dialog.get_values();
			return frappe.call({
				method: "erpnext.vehicles.doctype.vehicle_log.vehicle_log.make_odometer_log",
				args: {
					"vehicle": me.frm.doc.applies_to_vehicle,
					"odometer": cint(values.new_odometer),
					"date": values.date,
					"project": me.frm.doc.name,
				},
				callback: function (r) {
					if (!r.exc) {
						dialog.hide();
						me.frm.reload_doc();
					}
				}
			});
		});

		dialog.show();
	}

	reload_vehicle_details() {
		var me = this;
		if (!me.frm.doc.applies_to_vehicle) {
			return;
		}

		frappe.confirm(__('Are you sure you want to reload vehicle details?'),
			function() {
				frappe.call({
					method: "set_applies_to_details",
					doc: me.frm.doc,
					callback: function (r) {
						if (!r.exc) {
							me.frm.dirty();
							me.frm.refresh_fields();
						}
					}
				});
			}
		);
	}

	setup_vehicle_panel_fields() {
		this.toggle_vehicle_panels_visibility();
		this.set_was_panel_job();
	}

	is_panel_job(doc, cdt, cdn) {
		for (let d of (this.frm.doc.project_templates || [])) {
			if (d.name != cdn) {
				d.is_panel_job = 0;
			}
		}

		this.toggle_vehicle_panels_visibility();
		this.update_panel_template_description();
		this.set_was_panel_job();
	}
	project_templates_add() {
		this.toggle_vehicle_panels_visibility();
	}
	project_templates_remove() {
		this.toggle_vehicle_panels_visibility();
	}

	vehicle_panel() {
		this.update_panel_template_description();
	}
	vehicle_panel_side() {
		this.update_panel_template_description();
	}
	vehicle_panel_job() {
		this.update_panel_template_description();
	}
	panel_qty() {
		this.update_total_panel_qty();
	}
	vehicle_panels_add() {
		this.update_panel_template_description();
		this.update_total_panel_qty();
	}
	vehicle_panels_remove() {
		this.update_panel_template_description();
		this.update_total_panel_qty();
	}

	toggle_vehicle_panels_visibility() {
		if (!this.frm.fields_dict.vehicle_panels) {
			return;
		}

		var panel_template_rows = (this.frm.doc.project_templates || []).filter(el => el.is_panel_job == 1);
		this.frm.set_df_property('vehicle_panels', 'hidden', panel_template_rows.length ? 0 : 1);
		this.frm.set_df_property('total_panel_qty', 'hidden', panel_template_rows.length ? 0 : 1);
	}

	set_was_panel_job() {
		for (let d of (this.frm.doc.project_templates || [])) {
			d.was_panel_job = cint(d.is_panel_job);
		}
	}

	update_panel_template_description() {
		var description = [];
		for (let d of (this.frm.doc.vehicle_panels || [])) {
			if (d.vehicle_panel && d.vehicle_panel_job) {
				description.push(`${d.idx} -${d.vehicle_panel_side ? " " + d.vehicle_panel_side : ""} ${d.vehicle_panel} ${d.vehicle_panel_job}`);
			}
		}
		if (!description.length) {
			return;
		}

		description = description.join("<br>");

		for (let d of (this.frm.doc.project_templates || [])) {
			if (d.is_panel_job) {
				d.description = description;
			} else if (d.was_panel_job) {
				d.description = "";
			}
		}

		this.frm.refresh_field('project_templates');
	}

	update_total_panel_qty() {
		let total_panel_qty = 0;
		for (let d of (this.frm.doc.vehicle_panels || [])) {
			total_panel_qty += d.panel_qty;
		}
		this.frm.set_value("total_panel_qty", total_panel_qty);
	}
};

extend_cscript(cur_frm.cscript, new erpnext.projects.ProjectController({frm: cur_frm}));
