frappe.listview_settings['Transporter'] = {
	add_fields: ["status"],
	get_indicator: function (doc) {
		if (doc.status === "Enabled") {
			return [__(doc.status), "blue", "status,=," + doc.status];
		} else if (doc.status === "Disabled") {
			return [__(doc.status), "yellow", "status,=," + doc.status];
		} else if (doc.status === "Left") {
			return [__(doc.status), "grey", "status,=," + doc.status];
		}
	},
};
