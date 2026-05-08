import frappe


def execute():
	frappe.db.sql("""
		update `tabSales Invoice Item` cn_i
		inner join `tabSales Invoice` cn on cn.name = cn_i.parent
		inner join `tabSales Invoice Item` si_i on si_i.name = cn_i.sales_invoice_item
		set
			cn_i.proforma_invoice = si_i.proforma_invoice,
			cn_i.proforma_invoice_item = si_i.proforma_invoice_item
		where cn.is_return = 1
	""")

	proforma_invoices = frappe.db.sql_list("""
		select distinct cn_i.proforma_invoice
		from `tabSales Invoice Item` cn_i
		inner join `tabSales Invoice` cn on cn.name = cn_i.parent
		where cn.docstatus = 1 and cn.is_return = 1 and cn_i.proforma_invoice != '' and cn_i.proforma_invoice is not null
	""")

	for i, name in enumerate(proforma_invoices):
		print(f"{i+1}/{len(proforma_invoices)}: {name}")
		doc = frappe.get_doc("Proforma Invoice", name)
		doc.set_billing_status(update=True, update_modified=False)
		doc.set_status(update=True, update_modified=False)
