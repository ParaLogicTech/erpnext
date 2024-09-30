
def get_data():
	return {
		'fieldname': 'employee_advance',
		'non_standard_fieldnames': {
			'Journal Entry': 'reference_name',
			'Payment Entry': 'reference_name',
			'Expense Claim': 'reference_name',
		},
		'transactions': [
			{
				'label': ['Payment'],
				'items': ['Payment Entry', 'Journal Entry']
			},
			{
				'label': ['Adjustments'],
				'items': ['Expense Claim', 'Salary Slip']
			}
		]
	}
