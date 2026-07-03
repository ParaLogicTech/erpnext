# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from erpnext.accounts.report.customer_payment_ageing.customer_payment_ageing import PaymentAgeingReport


def execute(filters=None):
	return PaymentAgeingReport("Supplier", filters).run()
