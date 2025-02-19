import frappe


def execute():
	frappe.db.sql("""
		update `tabPayment Entry Reference` pref
		inner join `tabJournal Entry` je on je.name = pref.reference_name and pref.reference_doctype = 'Journal Entry'
		set pref.bill_no = je.bill_no
		where je.bill_no != '' and je.bill_no is not null
	""")
