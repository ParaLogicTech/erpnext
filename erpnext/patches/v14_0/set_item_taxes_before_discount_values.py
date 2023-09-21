import frappe


def execute():
	dts = [
		"Quotation", "Sales Order", "Delivery Note", "Sales Invoice",
		"Supplier Quotation", "Purchase Order", "Purchase Receipt", "Purchase Invoice",
	]

	for dt in dts:
		item_dt = f"{dt} Item"
		frappe.reload_doctype(dt, force=True)
		frappe.reload_doctype(item_dt, force=True)

		frappe.db.sql(f"""
			update `tab{item_dt}` i
			inner join `tab{dt}` p on p.name = i.parent
			set
				item_taxes_before_discount = item_taxes,
				base_item_taxes_before_discount = base_item_taxes,
				tax_inclusive_rate_before_discount = tax_inclusive_rate,
				base_tax_inclusive_rate_before_discount = base_tax_inclusive_rate,
				tax_inclusive_amount_before_discount = tax_inclusive_amount,
				base_tax_inclusive_amount_before_discount = base_tax_inclusive_amount
		""")

		names_with_discount = frappe.get_all(dt, filters={"discount_amount": ["!=", 0]}, pluck="name")
		for name in names_with_discount:
			doc = frappe.get_doc(dt, name)
			doc.calculate_taxes_and_totals()
			for d in doc.items:
				d.db_set({
					"item_taxes_before_discount": d.item_taxes_before_discount,
					"base_item_taxes_before_discount": d.base_item_taxes_before_discount,
					"tax_inclusive_rate_before_discount": d.tax_inclusive_rate_before_discount,
					"base_tax_inclusive_rate_before_discount": d.base_tax_inclusive_rate_before_discount,
					"tax_inclusive_amount_before_discount": d.tax_inclusive_amount_before_discount,
					"base_tax_inclusive_amount_before_discount": d.base_tax_inclusive_amount_before_discount,
				}, update_modified=False)
