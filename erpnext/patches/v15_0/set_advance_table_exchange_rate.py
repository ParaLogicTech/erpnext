import frappe


def execute():
	frappe.db.sql("""
		update `tabSales Invoice Advance` adv
		inner join `tabPayment Entry` pe on pe.name = adv.reference_name and adv.reference_type = 'Payment Entry'
		set adv.exchange_rate = pe.source_exchange_rate
	""")

	frappe.db.sql("""
		update `tabPurchase Invoice Advance` adv
		inner join `tabPayment Entry` pe on pe.name = adv.reference_name and adv.reference_type = 'Payment Entry'
		set adv.exchange_rate = pe.target_exchange_rate
	""")

	frappe.db.sql("""
		update `tabLanded Cost Voucher Advance` adv
		inner join `tabPayment Entry` pe on pe.name = adv.reference_name and adv.reference_type = 'Payment Entry'
		set adv.exchange_rate = pe.target_exchange_rate
	""")
