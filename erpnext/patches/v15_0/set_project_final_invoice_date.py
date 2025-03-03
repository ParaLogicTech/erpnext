import frappe


def execute():
	projects = frappe.get_all("Project", filters={"billing_status": "Fully Billed"}, pluck="name")
	for i, name in enumerate(projects):
		print(f"{i+1}/{len(projects)}: {name}")

		doc = frappe.get_doc("Project", name)
		sales_invoices = doc.get_sales_invoices()
		doc.final_invoice_date = None
		if sales_invoices and doc.billing_status == "Fully Billed":
			doc.final_invoice_date = sales_invoices[-1].posting_date

		if doc.final_invoice_date:
			doc.db_set("final_invoice_date", doc.final_invoice_date, update_modified=False)

		doc.clear_cache()
