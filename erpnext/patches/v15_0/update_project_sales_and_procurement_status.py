import frappe
import click


def execute():
	projects = frappe.get_all("Project", pluck="name")

	with click.progressbar(projects) as names:
		for name in names:
			doc = frappe.get_doc("Project", name)

			doc.set_sales_amount(update=False)
			doc.set_procurement_status(update=False)
			doc.set_billing_and_delivery_status(update=False)
			doc.set_pending_quotation_amount(update=False)

			fields_to_update = [
				"total_discount_amount",

				"part_sales_amount",
				"lubricant_sales_amount",
				"consumable_sales_amount",
				"paint_sales_amount",

				"hourly_labour_sales_amount",
				"package_sales_amount",

				"first_sales_order_date",
				"last_purchase_order_date",
				"last_purchase_receipt_date",
				"last_material_request_date",

				"pending_quotation_amount",

				"sold_time",
			]
			update_values = {f: doc.get(f) for f in fields_to_update}
			doc.db_set(update_values, update_modified=False)

			doc.clear_cache()
