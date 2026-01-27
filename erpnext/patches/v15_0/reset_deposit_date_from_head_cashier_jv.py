import frappe


def execute():
	frappe.db.sql("""
		update `tabJournal Entry Account` jea
		inner join `tabJournal Entry` je on je.name = jea.parent
		set jea.deposit_date = null
		where
			jea.deposit_date is not null
			and jea.reference_type = 'POS Closing Entry'
			and je.voucher_type != 'Deposit Entry'
	""")
