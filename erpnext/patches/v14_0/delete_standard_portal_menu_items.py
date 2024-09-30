import frappe


def execute():
	routes_to_remove = [
		"/personal-details", "/project", "/rfq", "/supplier-quotations", "/purchase-orders", "/purchase-invoices",
		"/quotations", "/orders", "/invoices", "/shipments", "/issues", "/addresses", "/timesheets", "/lab-test",
		"/prescription", "/patient-appointments", "/fees", "/newsletters", "/admissions", "/certification",
		"/material-requests", "/book_appointment"
	]

	doc = frappe.get_single("Portal Settings")
	rows_to_remove = []
	for d in doc.menu:
		if d.route in routes_to_remove:
			rows_to_remove.append(d)

	for d in rows_to_remove:
		doc.remove(d)

	if rows_to_remove:
		doc.save()
