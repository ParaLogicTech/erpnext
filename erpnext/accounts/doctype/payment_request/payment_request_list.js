frappe.listview_settings['Payment Request'] = {
	add_fields: ["status"],
	get_indicator: function(doc) {
		if (["Requested", "Initiated", "Payment Ordered"].includes(doc.status)) {
			return [__(doc.status), "blue", "status,=," + doc.status];
		} else if (doc.status == "Paid") {
			return [__(doc.status), "green", "status,=," + doc.status];
		} else if (doc.status == "Partially Paid") {
			return [__(doc.status), "yellow", "status,=," + doc.status];
		} else if (doc.status == "Failed") {
			return [__(doc.status), "orange", "status,=," + doc.status];
		}
	}
}
