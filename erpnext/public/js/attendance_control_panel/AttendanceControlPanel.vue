<template>

<div style="border: 1px solid gray;">
	<!-- Table -->
	<div class="table-wrapper">

		<table>
			<!-- Table Header -->
			<thead>
				<tr class="table-header">
					<th rowspan="2">#</th>
					<th rowspan="2">Employee Id</th>
					<th rowspan="2">Employee Name</th>
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
				<tr v-for="( obj, index ) in model.data">
					<th> {{ index + 1 }}</th>
					<th> {{ obj.employee }} </th>
					<th style="width: 85px;">{{ obj.employee_name }}</th>
					<AttendanceCell v-for="n in model.meta.total_days_in_month"
						:att="{'status_abbr': obj['days'][n]['status_abbr']}" />
					<td> {{ obj.total_present }}</td>
					<td> {{ obj.total_absent }}</td>
					<td> {{ obj.total_leave }}</td>
					<td> {{ obj.total_half_day }}</td>
					<td> {{ obj.total_late_entry }}</td>
					<td> {{ obj.total_early_exit }}</td>
					<td> {{ obj.total_lwp }}</td>
					<td> {{ obj.total_deduction }}</td>
				</tr>
			</tbody>

			<tbody>
				<tr v-for="( obj, index ) in model.data">
					<th> {{ index + 1 }}</th>
					<th> {{ obj.employee }} </th>
					<th style="width: 85px;">{{ obj.employee_name }}</th>
					<AttendanceCell v-for="n in model.meta.total_days_in_month"
						:att="{'status_abbr': obj['days'][n]['status_abbr']}" />
					<td> {{ obj.total_present }}</td>
					<td> {{ obj.total_absent }}</td>
					<td> {{ obj.total_leave }}</td>
					<td> {{ obj.total_half_day }}</td>
					<td> {{ obj.total_late_entry }}</td>
					<td> {{ obj.total_early_exit }}</td>
					<td> {{ obj.total_lwp }}</td>
					<td> {{ obj.total_deduction }}</td>
				</tr>
			</tbody>

			<tbody>
				<tr v-for="( obj, index ) in model.data">
					<th> {{ index + 1 }}</th>
					<th> {{ obj.employee }} </th>
					<th style="width: 85px;">{{ obj.employee_name }}</th>
					<AttendanceCell v-for="n in model.meta.total_days_in_month"
						:att="{'status_abbr': obj['days'][n]['status_abbr']}" />
					<td> {{ obj.total_present }}</td>
					<td> {{ obj.total_absent }}</td>
					<td> {{ obj.total_leave }}</td>
					<td> {{ obj.total_half_day }}</td>
					<td> {{ obj.total_late_entry }}</td>
					<td> {{ obj.total_early_exit }}</td>
					<td> {{ obj.total_lwp }}</td>
					<td> {{ obj.total_deduction }}</td>
				</tr>
			</tbody>

			<tbody>
				<tr v-for="( obj, index ) in model.data">
					<th> {{ index + 1 }}</th>
					<th> {{ obj.employee }} </th>
					<th style="width: 85px;">{{ obj.employee_name }}</th>
					<AttendanceCell v-for="n in model.meta.total_days_in_month"
						:att="{'status_abbr': obj['days'][n]['status_abbr']}" />
					<td> {{ obj.total_present }}</td>
					<td> {{ obj.total_absent }}</td>
					<td> {{ obj.total_leave }}</td>
					<td> {{ obj.total_half_day }}</td>
					<td> {{ obj.total_late_entry }}</td>
					<td> {{ obj.total_early_exit }}</td>
					<td> {{ obj.total_lwp }}</td>
					<td> {{ obj.total_deduction }}</td>
				</tr>
			</tbody>
		</table>
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
		}
	},


	methods: {
		fetch_model() {
			var me = this;
			frappe.call({
				method: "erpnext.hr.report.monthly_attendance_sheet.monthly_attendance_sheet.get_attendance_control_panel_data",
				args: {
					year: "2022",
					month: "Nov",
					company: "ParaLogic",
				},
				callback: function(r) {
					if(!r.exc && r.message) {
						console.log(r.message)
						me.model = r.message;
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
		}
	},

	created() {
		this.fetch_model();
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
		padding: 0.45rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 40px;
	}

	table thead {
		position: sticky;
		top: 0;
		z-index: 999;
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
		z-index: 2;
	}

	table tbody th:nth-child(3) {
		box-shadow: var(--shadow-base);
	}

</style>