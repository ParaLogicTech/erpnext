<template>
	<td>
		<div v-if="att.status_abbr">
			<a v-if="att.attendance"
				:href="frappe.utils.get_form_link('Attendance', att.attendance)"
				target="_blank"
				:style="get_style()"
			>
				{{ att.status_abbr }}
			</a>
			<span v-else :style="get_style()">{{ att.status_abbr }}</span>
		</div>
	</td>
</template>

<script>
export default {
	name: "AttendanceCell",

	props: {
		att: Object,
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
			const status = this.att.status;
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
			const status = this.att.status;

			if (status === "Holiday") {
				return "bold";
			} else {
				return "normal";
			}
		},

		get_opacity() {
			if (!this.att.attendance && this.att.status != "Holiday") {
				return 0.6;
			} else {
				return 1;
			}
		},
	}
}
</script>

