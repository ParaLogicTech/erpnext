import frappe
import click


fields_to_update = [
	"total_billable_amount",
	"customer_billable_amount",
	"total_billed_amount",

	"total_sales_amount",

	"material_sales_amount",
	"part_sales_amount",
	"lubricant_sales_amount",
	"consumable_sales_amount",
	"paint_sales_amount",

	"service_sales_amount",
	"labour_sales_amount",
	"hourly_labour_sales_amount",
	"package_sales_amount",
	"sublet_sales_amount",

	"total_cost",
	"material_cost_of_sales",
	"total_consumed_material_cost",
	"total_purchase_cost",
	"total_expense_claim",
	"timesheet_costing_amount",

	"pending_quotation_amount",
	"total_discount_amount",

	"sold_time",
	"actual_time",

	"final_invoice_date",
	"first_sales_order_date",
	"last_purchase_order_date",
	"last_purchase_receipt_date",
	"last_material_request_date",
	"procurement_status",
	"to_receive_materials",

	"gross_margin",
	"per_gross_margin",
]


def execute():
	projects = frappe.get_all("Project", pluck="name")

	with click.progressbar(projects) as names:
		for name in names:
			doc = frappe.get_doc("Project", name)
			doc.set_billing_and_delivery_status(update=False)
			doc.set_procurement_status(update=False)
			doc.set_costing(update=False)

			update_values = {f: doc.get(f) for f in fields_to_update}
			doc.db_set(update_values, update_modified=False)

			doc.clear_cache()
