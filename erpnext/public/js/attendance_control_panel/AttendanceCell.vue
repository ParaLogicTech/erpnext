<template>
	<td>
		<div v-if="attendance_data.status_abbr">
			<span :id="'att-' + employee_data.employee + '-' + day_of_month">
				<a v-if="attendance_data.attendance"
					:style="get_style()"
					:href="frappe.utils.get_form_link('Attendance', attendance_data.attendance)"
					target="_blank"
				>
					{{ attendance_data.status_abbr }}
				</a>
				<span v-else :style="get_style()">{{ attendance_data.status_abbr }}</span>
			</span>
			<b-popover :target="'att-' + employee_data.employee + '-' + day_of_month"
				triggers="hover focus"
				placement="bottom"
				boundary="viewport"
				custom-class="attendance-popover"
			>
				<div class="container-flex">
					<a :href="frappe.utils.get_form_link('Attendance', attendance_data.attendance)"
						target="_blank"
						>
						<h4 class="indicator m-0"
							:class="get_color()"
							:style="{'color': 'var(--indicator-dot-' + get_color() + ')'}"
						>
							{{ attendance_data.status }}
						</h4>
					</a>
					<hr class="bottom-border mb-0">
					<div class="attendance-wrapper pt-2">
						<div>
							<div class="attendance-label">Employee Id</div>
							<a
								:href="frappe.utils.get_form_link('Employee', employee_data.employee)"
								target="_blank"
							>
								<div>{{ employee_data.employee }}</div>
							</a>
						</div>

						<div>
							<div class="attendance-label">Name</div>
							<div>{{ employee_data.employee_name }}</div>
						</div>

						<div>
							<div class="attendance-label">Designation</div>
							<div>{{ employee_data.designation }}</div>
						</div>

						<div>
							<div class="attendance-label">Department</div>
							<div>{{ employee_data.department }}</div>
						</div>
					</div>

				</div>
			</b-popover>
		</div>
	</td>
</template>

<script>

export default {
	name: "AttendanceCell",

	props: {
		employee_data: Object,
		attendance_data: Object,
		day_of_month: Number,
	},

	methods: {
		get_style() {
			return {
				color: this.get_color(),
				fontWeight: this.get_font_weight(),
				opacity: this.get_opacity(),
			}
		},

		get_color() {
			const status = this.attendance_data.status;
			if (status === "Present") {
				return "green";
			} else if (status === "Absent") {
				return "red";
			} else if (status === "Half Day") {
				return "orange";
			} else if (status === "On Leave") {
				return "blue";
			} else {
				return "inherit";
			}
		},

		get_font_weight() {
			const status = this.attendance_data.status;

			if (status === "Holiday") {
				return "bold";
			} else {
				return "normal";
			}
		},

		get_opacity() {
			if (!this.attendance_data.attendance && this.attendance_data.status != "Holiday") {
				return 0.6;
			} else {
				return 1;
			}
		},
	}
}
</script>

<style>
	.attendance-popover {
		width: 400px;
	}

	.attendance-wrapper {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		grid-template-rows: 1fr;
		grid-row-gap: 10px;
	}

	.attendance-label {
		font-size: 0.7rem;
		font-weight: bold;
	}

	.bottom-border {
		margin-left: -10px;
		margin-right: -10px;
	}

</style>