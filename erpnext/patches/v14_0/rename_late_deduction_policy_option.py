import frappe


def execute():
	frappe.reload_doctype("Leave Policy")
	frappe.db.sql("""
		update `tabLeave Policy`
		set late_deduction_policy = 'No of Late Days as Leave Without Pay'
		where late_deduction_policy = 'n Late Days = 1 Leave Without Pay'
	""")
	frappe.db.sql("""
		update `tabLeave Policy`
		set late_lwp_multiplier = 1
	""")
