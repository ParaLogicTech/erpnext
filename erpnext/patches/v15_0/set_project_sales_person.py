import frappe


def execute():
	frappe.db.sql("""
		update `tabProject` p
		inner join `tabAppointment` apt on apt.name = p.appointment
		set p.sales_person = apt.sales_person
		where p.sales_person is null or p.sales_person = ''
	""")

	frappe.db.sql("""
		update `tabProject` p
		set p.sales_person = p.service_advisor
		where p.sales_person is null or p.sales_person = ''
	""")

	frappe.db.sql("""
		update `tabProject` p
		inner join `tabAppointment` apt on apt.name = p.appointment
		set p.opportunity = apt.opportunity
	""")

	service_advisors = frappe.db.sql_list("select distinct service_advisor from `tabProject`")
	if service_advisors:
		frappe.db.sql("update `tabSales Person` set is_service_advisor = 1 where name in %s", [service_advisors])
