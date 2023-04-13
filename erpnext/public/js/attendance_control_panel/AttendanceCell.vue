
<template>
    <td :style="{color: get_color()}">{{ att.status_abbr }}</td>
</template>

<script>

export default {
	name: "AttendanceCell",

	props: {
		att: Object,
	},

	methods: {

		get_color() {
			const status = this.att.status_abbr;
			console.log(status)

			if (status === "P") {
				return "green";
			}

			else if (status === "A") {
				return "red";
			}

			else if (status === "HD") {
				return "orange";
			}

			else {
				return "black";
			}
		}
	}
}
</script>

