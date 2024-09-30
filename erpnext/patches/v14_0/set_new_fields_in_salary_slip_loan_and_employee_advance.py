import frappe
from frappe.model.utils.rename_field import rename_field

def execute():
	frappe.reload_doc("hr", "doctype", "salary_slip_loan")
	frappe.reload_doc("hr", "doctype", "salary_slip_employee_advance")

	rename_field("Salary Slip Loan", "total_payment", "repayment_amount")
	rename_field("Salary Slip Employee Advance", "balance_amount", "advance_amount")

	frappe.db.sql("""
		UPDATE `tabSalary Slip Loan` cssl
		INNER JOIN `tabRepayment Schedule` rps ON rps.name = cssl.loan_repayment_detail
		INNER JOIN `tabLoan` loan ON loan.name = rps.parent
		SET
			cssl.loan_type = loan.loan_type,
			cssl.disbursement_date = loan.disbursement_date,
			cssl.total_loan_amount = loan.total_payment,
			cssl.pending_loan_amount = cssl.repayment_amount + rps.balance_loan_amount,
			cssl.balance_amount = rps.balance_loan_amount
	""")

	frappe.db.sql("""
		UPDATE `tabSalary Slip Employee Advance` advance
		SET advance.balance_amount = advance.advance_amount - advance.allocated_amount
	""")


	for d in frappe.get_all('Salary Slip', filters={'docstatus': 0}):
		frappe.get_doc('Salary Slip', d.name).save()
