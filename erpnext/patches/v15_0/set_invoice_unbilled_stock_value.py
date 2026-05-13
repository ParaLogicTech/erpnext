import frappe
import click


def execute():
	invoices = frappe.db.sql_list("""
		select distinct si.name
		from `tabSales Invoice Item` i
		inner join `tabSales Invoice` si on si.name = i.parent
		where i.unbilled_stock_account is not null and i.unbilled_stock_account != '' and si.docstatus = 1
	""")

	with click.progressbar(invoices) as names:
		for name in names:
			doc = frappe.get_doc("Sales Invoice", name)
			doc.set_unbilled_stock_value(update=True, update_modified=False)
			doc.clear_cache()
