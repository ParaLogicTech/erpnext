
<template>
    <td :style="{color: get_color(), fontWeight: get_font_weight()}">{{ att.status_abbr }}</td>
</template>

<script>

export default {
	name: "AttendanceCell",

	props: {
		att: Object,
	},

	methods: {

		// for Colors
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

		// for Fonts
		get_font_weight() {
			const status = this.att.status;

			if (status === "Holiday") {
				return "bold";
			} else {
				return "normal";
			}
		}
	}
}
</script>

