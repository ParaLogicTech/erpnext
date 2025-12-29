import frappe


def execute():
	frappe.db.sql("""
		update `tabService Template Task`
		set expected_days = 1
		where expected_days <= 0
	""")

	frappe.db.sql("""
		update `tabTask`
		set exp_start_date = date(creation)
		where exp_start_date is null
	""")

	frappe.db.sql("""
		update `tabTask`
		set exp_end_date = if(act_end_date is not null, date(act_end_date), exp_start_date)
		where exp_end_date is null
	""")

	frappe.db.sql("""
		update `tabTask`
		set exp_end_date = exp_start_date
		where exp_end_date < exp_start_date
	""")
	