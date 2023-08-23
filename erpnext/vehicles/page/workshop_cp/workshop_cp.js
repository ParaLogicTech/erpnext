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
					{ fieldname: 'task_status', label: __('Status') },
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
				options: [' ', 'Unassigned', 'Not Started', 'In Progress', 'Paused', 'Completed', 'Ready']

			},
		];

		for (let field of filter_fields) {
			field.onchange = () => this.debounced_refresh();
		}

		return filter_fields;
	}

	setup_tabbed_layout() {
		this.dashboard_tab = this.page.main.find("#dashboard-content");
		this.vehicles_tab = this.page.main.find("#vehicles-content");

		this.dashboard_tab.append(frappe.render_template("workshop_cp_dashboard"));
		this.vehicles_tab.append(frappe.render_template("workshop_cp_vehicles"));
	}

	bind_events() {
		$(this.parent).on("click", ".clear-filters", () => this.clear_filters());

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

	get_list_row_html(doc) {
		return frappe.render_template("workshop_cp_vehicle_row", {
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
