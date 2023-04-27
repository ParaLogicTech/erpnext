<template>

<div v-if="error" class="d-flex justify-content-center align-items-center text-muted py-5">
	{{ error }}
</div>

<div v-else-if="model.data.length === 0" class="d-flex justify-content-center align-items-center text-muted py-5">
	<div>Nothing to show</div>
</div>

<div v-else>
	<div style="border: 1px solid gray;">
		<!-- Table -->
		<div class="table-wrapper">

			<table>
				<!-- Table Header -->
				<thead>
					<tr class="table-header">
						<th rowspan="2">#</th>
						<th rowspan="2">ID</th>
						<th rowspan="2">Name</th>
						<th v-for="n in model.meta.total_days_in_month" >{{ n }}</th>
						<th rowspan="2">Total<br/>Present</th>
						<th rowspan="2">Total<br/>Absents</th>
						<th rowspan="2">Total<br/>Leaves</th>
						<th rowspan="2">Total<br/>Half<br/>Days</th>
						<th rowspan="2">Total<br/>Late<br/>Entry</th>
						<th rowspan="2">Total<br/>Early<br/>Exit</th>
						<th rowspan="2">Total<br/>LWP</th>
						<th rowspan="2">Total<br/>Deduction</th>
					</tr>
					<tr>
						<th v-for="day in get_day_range( model.meta )" >{{ day }}</th>
					</tr>
				</thead>

				<!-- Table Body -->
				<tbody>
					<tr v-for="obj, index in model.data">
						<th>{{ index + 1 }}</th>
						<th><a href="" target="_blank">{{ obj.employee }}</a></th>
						<th style="width: 85px;">{{ obj.employee_name }}</th>
						<AttendanceCell v-for="n in model.meta.total_days_in_month" :att="obj['days'][n]" />
						<td>
							<a :href="get_link_to_checkin_sheet(obj)"
								:style="{ color: obj.total_present > 0 ? 'green' : 'inherit' }"
								target="_blank"
							>
								{{ obj.total_present }}
							</a>
						</td>
						<td>
							<a :href="get_link_to_checkin_sheet(obj)"
								:style="{ color: obj.total_absent > 0 ? 'red' : 'inherit' }"
								target="_blank"
							>
								{{ obj.total_absent }}
							</a>
						</td>
						<td>
							<a :href="get_link_to_checkin_sheet(obj)"
								:style="{ color: obj.total_leave > 0 ? 'blue' : 'inherit' }"
								target="_blank"
							>
								{{ obj.total_leave }}
							</a>
						</td>
						<td>
							<a :href="get_link_to_checkin_sheet(obj)"
								:style="{ color: obj.total_half_day > 0 ? 'orange' : 'inherit' }"
								target="_blank"
							>
								{{ obj.total_half_day }}
							</a>
						</td>
						<td>
							<a :href="get_link_to_checkin_sheet(obj)"
								:style="{ color: obj.total_late_entry > 0 ? 'orange' : 'inherit' }"
								target="_blank"
							>
								{{ obj.total_late_entry }}
							</a>
						</td>
						<td>
							<a :href="get_link_to_checkin_sheet(obj)"
								:style="{ color: obj.total_early_exit > 0 ? 'orange' : 'inherit' }"
								target="_blank"
							>
								{{ obj.total_early_exit }}
							</a>
						</td>
						<td>{{ obj.total_lwp }}</td>
						<td :style="{ color: obj.total_early_exit > 0 ? 'red' : 'inherit' }">{{ obj.total_deduction }}</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</div>

</template> 

<script>
import AttendanceCell from './AttendanceCell.vue';

export default {
	name: "AttendanceControlPanel",

	components: {
		AttendanceCell,
	},

	data() {
		return {
			loaded: false,
			model: {
				data: [],
				meta: {},
			},
			error: '',
		}
	},

	methods: {
		fetch_model() {
			let me = this;
			this.error = null;
			let filters = this.page.get_form_values();
			let reqd_fields = Object.values(this.page.fields_dict).filter(d => d.df.reqd).map(d => d.df.fieldname);

			for (let fieldname of reqd_fields) {
				let field = this.page.fields_dict[fieldname];

				if (!field.value) {
					this.error = `Please set filters`
				}
			}

			if (this.error) return;

			frappe.call({
				method: "erpnext.hr.report.monthly_attendance_sheet.monthly_attendance_sheet.get_attendance_control_panel_data",
				args: {
					filters: {
						company: filters.company,
						year: filters.year,
						month: filters.month,
						employee: filters.employee,
					}
				},
				callback: function(r) {
					if(!r.exc && r.message) {
						me.model = r.message;

						let data = [];
						let key_list = Object.keys(me.model.data);
						key_list.sort();

						for (let key of key_list) {
							data.push(me.model.data[key]);
						}

						me.model.data = data;
						console.log(data)
						me.loaded = true;
					}
				}
			});
		},

		// Day Range Calculation
		get_day_range() {
			var day_list = [];
			var current_date = moment(this.model.meta.from_date);
			var end_date = moment(this.model.meta.to_date);

			while (current_date <= end_date) {
				day_list.push(current_date.format('ddd'))
				current_date.add(1, 'd')
			}

			return day_list
		},

		get_link_to_checkin_sheet(data) {
			return `/app/query-report/Employee Checkin Sheet?employee=${encodeURIComponent(data.employee)}&from_date=${data.from_date}&to_date=${data.to_date}`
		}
	},

	created() {
		this.page = cur_page.page.page;
		this.fetch_model();

		$(this.page.parent).on("reload-attendance", () => {
			this.fetch_model();
		});
	}
};
</script>

<style>

	/* Table Css */
	.search-fields {
		padding: .4rem;
		border: 1px solid grey;
		background-color: var(--gray-100);
	}

	.table-wrapper {
		width: 100%;
		max-height: 600px;
		overflow-x: scroll;
		overflow-y: scroll;
	}

	table {
		white-space: nowrap;
		border-collapse: separate;
		border-spacing: 0;
		table-layout: fixed;
	}

	table td,
	table th {
		border: .5px solid var(--dark);
		padding: 0.3rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 40px;
	}

	table thead {
		position: sticky;
		top: 0;
		z-index: 3;
		background: var(--gray-100);
		text-align: center;
		box-shadow: var(--shadow-base);
	}

	table td {
		background: var(--white);
		text-align: center;
	}

	table tbody th {
		position: relative;
		text-align: center;
	}

	table .table-header th:nth-child(-n+3) {
		position: sticky;
		left: 0;
		z-index: 2;
		background: var(--gray-100);
	}

	table tbody th {
		position: sticky;
		left: 0;
		background: var(--gray-100);
		font-weight: normal;
		z-index: 2;
	}

	table tbody th:nth-child(3) {
		box-shadow: var(--shadow-base);
		text-align: left;
	}

</style>