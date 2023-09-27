frappe.pages["workshop-cp"].on_page_load = (wrapper) => {
	frappe.workshop_cp = new WorkshopCP(wrapper);
};

class WorkshopCP {
	constructor(wrapper) {
		frappe.ui.make_app_page({
			parent: wrapper,
			title: 'Workshop Control Panel',
			single_column: true,
			card_layout: true,
		});

		this.parent = wrapper;
		this.page = this.parent.page;

		$(this.page.parent).addClass("workshop-cp");

		this.make();
	}

	make() {
		this.page_name = frappe.get_route_str();
		this.setup_indicator();
		this.setup_buttons();
		this.setup_filters();
		this.setup_list_wrapper();
		this.add_clear_filters_button();
		this.setup_sort_selector()
		this.page.main.append(frappe.render_template("workshop_cp_layout"));
		this.setup_tabbed_layout();
		this.bind_events();

		this.initialized = true;
	}

	setup_buttons() {
		this.refresh_button = this.page.add_button(__("Refresh"), () => this.refresh(), {
			icon: "refresh"
		});
	}

	setup_filters() {
		let filter_area = this.page.page_form;

		this.$filter_section = $(`<div class="standard-filter-section flex"></div>`).appendTo(filter_area);

		let filter_fields = this.get_filter_fields();
		this.filters = filter_fields.map((df) => {
			if (df.fieldtype === "Break") return;

			let f = this.page.add_field(df, this.$filter_section);

			if (df.default) {
				f.set_input(df.default);
			}

			if (df.get_query) f.get_query = df.get_query;
			if (df.on_change) f.on_change = df.on_change;

			f = Object.assign(f, df);
			return f;
		});
	}


	setup_list_wrapper() {
		this.$frappe_list = $('<div class="frappe-list"></div>').appendTo(this.page.main);
	}

	add_clear_filters_button() {
		$(`<div class="tag-filters-area">
				<div class ="active-tag-filters">
					<button class="btn btn-default btn-xs filter-button clear-filters">Clear Filters</button>
				</div>
			</div>`).appendTo(this.$frappe_list);
	}

	setup_sort_selector() {
		this.sort_selector = new frappe.ui.SortSelector({
			parent: this.$frappe_list,
			args: {
				sort_by: "vehicle_received_date",
				sort_order: "asc",
				options: [
					{ fieldname: 'vehicle_received_date', label: __('Vehicle Received Date') },
					{ fieldname: 'expected_delivery_date', label: __('Expected Delivery Date') },
					{ fieldname: 'name', label: __('Project') },
					{ fieldname: 'tasks_status', label: __('Status') },
				]
			},
			change: () => {
				this.refresh();
			}
		});
	}

	get_filter_fields() {
		let filter_fields = [
			{
				label: __("Workshop"),
				fieldname: "project_workshop",
				fieldtype: "Link",
				options: "Project Workshop",
			},
			{
				label: __("Project"),
				fieldname: "name",
				fieldtype: "Link",
				options: "Project",
			},
			{
				label: "Model/Variant",
				fieldname: "applies_to_item",
				fieldtype: "Link",
				options: "Item",
				get_query: function () {
					return {
						query: "erpnext.controllers.queries.item_query",
						filters: { "is_vehicle": 1, "include_disabled": 1, "include_templates": 1 }
					};
				}
			},
			{
				label: "Vehicle",
				fieldname: "applies_to_vehicle",
				fieldtype: "Link",
				options: "Vehicle",
			},
			{
				label: __("Customer"),
				fieldname: "customer",
				fieldtype: "Link",
				options: "Customer",
			},
			{
				label: "Status",
				fieldname: "status",
				fieldtype: "Select",
				options: ['', 'No Tasks', 'Not Started', 'In Progress', 'On Hold', 'Completed', 'Ready']

			},
		];

		for (let field of filter_fields) {
			field.onchange = () => this.debounced_refresh();
		}

		return filter_fields;
	}

	setup_tabbed_layout() {
		// this.dashboard_tab = this.page.main.find("#dashboard-content");
		this.vehicles_tab = this.page.main.find("#vehicles-content");
		this.tasks_tab = this.page.main.find("#tasks-content");

		// this.dashboard_tab.append(frappe.render_template("workshop_cp_dashboard"));
		this.vehicles_tab.append(frappe.render_template("workshop_cp_vehicles"));
		this.tasks_tab.append(frappe.render_template("workshop_cp_tasks"));
	}

	bind_events() {
		$(this.parent).on("click", ".clear-filters", () => this.clear_filters());
		$(this.parent).on("click", ".create_template_tasks", (e) => this.create_template_tasks(e));
		$(this.parent).on("click", ".create_tasks", (e) => this.create_tasks(e));
		$(this.parent).on("click", ".mark_as_ready", (e) => this.update_project_ready_to_close(e));
		$(this.parent).on("click", ".reopen", (e) => this.update_reopen_project_status(e));
		$(this.parent).on("click", ".technician", (e) => this.assign_technician(e));
		$(this.parent).on("click", ".unassigned_technician", (e) => this.reassign_technician(e));
		$(this.parent).on("click", ".delete_task", (e) => this.delete_task(e));
		$(this.parent).on("click", ".edit_task", (e) => this.edit_task(e));
		$(this.parent).on("click", ".start_task", (e) => this.start_task(e));
		$(this.parent).on("click", ".pause_task", (e) => this.pause_task(e));
		$(this.parent).on("click", ".complete_task", (e) => this.complete_task(e));
		$(this.parent).on("click", ".resume_task", (e) => this.resume_task(e));

		this.setup_realtime_updates();

		$(this.parent).bind("show", () => {
			if (this.initialized && this.is_visible()) {
				this.refresh();
			}
		});
	}

	async clear_filters() {
		this._no_refresh = true;
		for (let field of Object.values(this.page.fields_dict)) {
			await field.set_value(null);
		}
		this._no_refresh = false;
		await this.refresh();
	}

	async create_template_tasks(e) {
		let project = $(e.target).attr('data-project');
		return frappe.call({
			method: "erpnext.vehicles.page.workshop_cp.workshop_cp.create_template_tasks",
			args: {
				"project": project,
			},
		})
	}

	create_task(e) {
			let project = $(e.target).attr('data-project');
			var d = new frappe.ui.Dialog({
				title: __('Create Task'),
				fields: [
					{
						"label" : "Subject",
						"fieldname": "subject",
						"fieldtype": "Data",
						"options": "Task",
						"reqd": 1,
					},
					{
						"label": __("Project"),
						"fieldname": "project",
						"fieldtype": "Link",
						"options": "Project",
						"read_only": 1,
						"default": project,
						"reqd": 1,
					},
					{
						"label" : "Standard Time",
						"fieldname": "standard_time",
						"fieldtype": "Int",
					},
				],
				primary_action: function() {
					let values = d.get_values();
					frappe.call({
						method: "erpnext.vehicles.page.workshop_cp.workshop_cp.create_custom_tasks",
						args: {
							subject: values.subject,
							project: values.project,
						},
					});
					d.hide()
				},
				primary_action_label: __('Create')
			});
			d.show();
	}

	assign_technician(e) {
		let task = $(e.target).attr('data-task');
		let subject = $(e.target).attr('data-subject');
		var d = new frappe.ui.Dialog({
			title: __('Assign Technician'),
			fields: [
				{
					"label": "Task",
					"fieldname": "name",
					"fieldtype": "Link",
					"options": "Task",
					"default": task,
					"read_only": 1,
					"reqd": 1,
				},
				{
					"label" : "Subject",
					"fieldname": "subject",
					"fieldtype": "Data",
					"default": subject,
					"read_only": 1,
				},
				{
					"label" : "Technician",
					"fieldname": "employee",
					"fieldtype": "Link",
					"options": "Employee",
					"onchange": () => {
						let employee = d.get_value('employee');
						if (employee) {
							frappe.db.get_value("Employee", employee, ['employee_name'], (r) => {
								if (r) {
									d.set_values(r);
								}
							});
						} else {
							d.set_value('employee_name', '');
						}
					}
				},
				{
					"label" : "Technician Name",
					"fieldname": "employee_name",
					"fieldtype": "Data",
					"read_only": 1,
				},
			],
			primary_action: function() {
				let values = d.get_values();
				frappe.call({
					method: "erpnext.vehicles.page.workshop_cp.workshop_cp.assign_technician_task",
					args: {
						task: values.name,
						technician: values.employee,
						subject: values.subject

					},
				});
				d.hide()
			},
			primary_action_label: __('Assign')
		});
		d.show();
	}
	reassign_technician(e) {
		let task = $(e.target).attr('data-task');
		let technician = $(e.target).attr('data-technician');
		let technician_name = $(e.target).attr('data-technician_name');
		var d = new frappe.ui.Dialog({
			title: __('Edit Task'),
			fields: [
				{
					"label": "Task",
					"fieldname": "name",
					"fieldtype": "Link",
					"options": "Task",
					"default": task,
					"read_only": 1,
					"reqd": 1,
				},
				{
					"label" : "Technician",
					"fieldname": "employee",
					"fieldtype": "Link",
					"options": "Employee",
					"default": technician,
					"onchange": () => {
						let employee = d.get_value('employee');
						if (employee) {
							frappe.db.get_value("Employee", employee, ['employee_name'], (r) => {
								if (r) {
									d.set_values(r);
								}
							});
						} else {
							d.set_value('employee_name', '');
						}
					}
				},
				{
					"label" : "Technician Name",
					"fieldname": "employee_name",
					"fieldtype": "Data",
					"default": technician_name,
					"read_only": 1,
				},
			],
			primary_action: function() {
				let values = d.get_values();
				frappe.call({
					method: "erpnext.vehicles.page.workshop_cp.workshop_cp.reassign_technician_task",
					args: {
						task: values.name,
						technician: values.employee || '',
					},
				});
				d.hide()
			},
			primary_action_label: __('Save')
		});
		d.show();

	}

	async delete_task(e) {
		let task = $(e.target).attr('data-task');
		return frappe.call({
			method: "erpnext.vehicles.page.workshop_cp.workshop_cp.delete_task",
			args: {
				"task": task,
			},
		});
	}

	edit_task(e) {
		let task = $(e.target).attr('data-task');
		let subject = $(e.target).attr('data-subject');
		var d = new frappe.ui.Dialog({
			title: __('Edit Task'),
			fields: [
				{
					"label": "Task",
					"fieldname": "name",
					"fieldtype": "Link",
					"options": "Task",
					"default": task,
					"read_only": 1,
					"reqd": 1,
				},
				{
					"label" : "Subject",
					"fieldname": "subject",
					"fieldtype": "Data",
					"default": subject,
				},
			],
			primary_action: function() {
				let values = d.get_values();
				frappe.call({
					method: "erpnext.vehicles.page.workshop_cp.workshop_cp.edit_task",
					args: {
						task: values.name,
						subject: values.subject
					},
				});
				d.hide()
			},
			primary_action_label: __('Save')
		});
		d.show();

	}

	async start_task(e) {
		let task = $(e.target).attr('data-task');
		return frappe.call({
			method: "erpnext.vehicles.page.workshop_cp.workshop_cp.start_task",
			args: {
				task: task,
			},
		});

	}

	async pause_task(e) {
		let task = $(e.target).attr('data-task');
		return frappe.call({
			method: "erpnext.vehicles.page.workshop_cp.workshop_cp.pause_task",
			args: {
				task: task,
			},
		});

	}

	async complete_task(e) {
		let task = $(e.target).attr('data-task');
		return frappe.call({
			method: "erpnext.vehicles.page.workshop_cp.workshop_cp.complete_task",
			args: {
				task: task,
			},
		});

	}

	async resume_task(e) {
		let task = $(e.target).attr('data-task');
		return frappe.call({
			method: "erpnext.vehicles.page.workshop_cp.workshop_cp.resume_task",
			args: {
				task: task,
			},
		});

	}

	async update_project_ready_to_close(e) {
		let project = $(e.target).attr('data-project');
		return frappe.call({
			method: "erpnext.projects.doctype.project.project.set_project_ready_to_close",
			args: {
				"project": project,
			},
		});
	}

	async update_reopen_project_status(e) {
		let project = $(e.target).attr('data-project');
		return frappe.call({
			method: "erpnext.projects.doctype.project.project.reopen_project_status",
			args: {
				"project": project,
			},
		});
	}

	async refresh() {
		if (this._no_refresh) {
			return;
		}

		if (this.auto_refresh) {
			clearTimeout(this.auto_refresh);
		}
	
		this.refreshing = true;
		this.render_last_updated();

		try {
			let r = await this.fetch_data();
			this.data = r.message;
		} catch {
			this.render_last_updated();
		} finally {
			this.refreshing = false;
			this.auto_refresh = setTimeout(() => {
				if (this.is_visible()) {
					this.debounced_refresh();
				}
			}, 30000);
		}

		this.render();	
	}

	debounced_refresh = frappe.utils.debounce(() => this.refresh(), 200)

	async fetch_data() {
		let filters = this.get_filter_values();
		let sort_by = this.sort_selector.sort_by;
		let sort_order = this.sort_selector.sort_order;

		return frappe.call({
			method: "erpnext.vehicles.page.workshop_cp.workshop_cp.get_workshop_cp_data",
			args: {
				filters: filters,
				sort_by: sort_by,
				sort_order: sort_order,
			},
			callback: (r) => {
				this.last_updated = frappe.datetime.now_datetime();
			}
		});
	}

	render() {
		this.render_last_updated();
		this.render_dashboard_tab();
		this.render_vehicles_tab();
		this.render_tasks_tab();
	}

	render_last_updated() {
		if (!this.$refresh_wrapper) {
			this.$refresh_wrapper = $(`<div class="refresh-container text-muted"></div>`).prependTo(this.page.custom_actions);

			this.$refreshing_wrapper = $(`<div>Refreshing...</div>`).appendTo(this.$refresh_wrapper);

			this.$last_updated_wrapper = $(`<div>Updated </div>`).appendTo(this.$refresh_wrapper);
			this.$last_updated_timestamp =  $(`<span class="frappe-timestamp"></span>`).appendTo(this.$last_updated_wrapper);
		}

		this.$refreshing_wrapper.toggle(this.refreshing);
		this.$last_updated_wrapper.toggle(!this.refreshing);

		this.$last_updated_timestamp.attr('data-timestamp', this.last_updated);
		this.$last_updated_timestamp.html(frappe.datetime.prettyDate(this.last_updated));
	}

	render_dashboard_tab() {
	}

	render_vehicles_tab() {
		// clear rows
		this.vehicles_tab.find(".vehicle-table tbody").empty();

		if (this.data.projects.length > 0) {
			// append rows
			let rows_html = this.data.projects.map((doc, i) => {
				doc._idx = i;
				return this.get_list_row_html(doc);
			}).join("");

			this.vehicles_tab.find(".vehicle-table tbody").append(rows_html);
		}
	}

	render_tasks_tab() {
		this.tasks_tab.find(".task-table tbody").empty();

		if (this.data.tasks.length > 0) {

			let rows_html = this.data.tasks.map((doc, i) => {
				doc._idx = i;
				return this.get_task_list_row_html(doc);
			}).join("");

			this.tasks_tab.find(".task-table tbody").append(rows_html);
		}
	}

	get_list_row_html(doc) {
		return frappe.render_template("workshop_cp_vehicle_row", {
			"doc": doc,
		});
	}

	get_task_list_row_html(doc) {
		return frappe.render_template("workshop_cp_task_row", {
			"doc": doc,
		});
	}

	get_filter_values() {
		return this.page.get_form_values();
	}

	setup_indicator() {
		this.connection_status = false;
		this.check_internet_connection();

		// TODO use socketio for checking internet connectivity
		// frappe.realtime.on("connect", (data) => {
		// 	console.log("CONNECTED")
		// });
		// frappe.realtime.on("disconnect", (data) => {
		// 	console.log("DISCONNECTED!!!")
		// });

		setInterval(() => {
			this.check_internet_connection();
		}, 5000);
	}

	check_internet_connection() {
		if (!this.is_visible()) {
			return;
		}

		return frappe.call({
			method: "frappe.handler.ping",
			callback: (r) => {
				if (r.message) {
					this.connection_status = true;
					this.set_indicator();
				}
			},
			error: () => {
				this.connection_status = false;
				this.set_indicator();
			},
		})
	}

	setup_realtime_updates() {
		frappe.socketio.doctype_subscribe('Project');
		frappe.socketio.doctype_subscribe('Task');
		frappe.realtime.on("list_update", (data) => {
			if (!this.is_visible()) {
				return;
			}
			if (data?.doctype !== 'Project'){
				return;
			}
			this.debounced_refresh();
		});
	}

	set_indicator() {
		if (this.connection_status) {
			this.page.set_indicator(__("Online"), "green");
		} else {
			this.page.set_indicator(__("Offline"), "red");
		}
	}

	is_visible() {
		return frappe.get_route_str() == this.page_name;
	}
}
