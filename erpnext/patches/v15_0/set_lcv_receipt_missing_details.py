import frappe


def execute():
	frappe.db.sql("""
		update `tabLanded Cost Purchase Receipt` lcpr
		inner join `tabPurchase Receipt` prec on prec.name = lcpr.receipt_document and lcpr.receipt_document_type = 'Purchase Receipt'
		set lcpr.bill_no = prec.bill_no
	""")

	frappe.db.sql("""
		update `tabLanded Cost Purchase Receipt` lcpr
		inner join `tabPurchase Invoice` pinv on pinv.name = lcpr.receipt_document and lcpr.receipt_document_type = 'Purchase Invoice'
		set lcpr.bill_no = pinv.bill_no
	""")

	frappe.db.sql("""
		update `tabLanded Cost Purchase Receipt` lcpr
		inner join `tabSupplier` sup on sup.name = lcpr.supplier
		set lcpr.supplier_name = sup.supplier_name
	""")
