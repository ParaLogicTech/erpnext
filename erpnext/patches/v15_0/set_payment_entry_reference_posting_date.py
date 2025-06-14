import frappe


def execute():
	join = {
		"Sales Invoice": "posting_date",
		"Purchase Invoice": "posting_date",
		"Landed Cost Voucher": "posting_date",
		"Journal Entry": "posting_date",
		"Sales Order": "transaction_date",
		"Purchase Order": "transaction_date",
		"Expense Claim": "posting_date",
		"Employee Advance": "posting_date",
	}

	for dt, date_field in join.items():
		frappe.db.sql(f"""
			update `tabPayment Entry Reference` pref
			inner join `tab{dt}` doc on doc.name = pref.reference_name and pref.reference_doctype = '{dt}'
			set pref.posting_date = doc.`{date_field}`
		""")
