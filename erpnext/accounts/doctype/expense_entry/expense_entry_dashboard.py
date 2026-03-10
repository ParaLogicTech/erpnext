from frappe import _


def get_data():
	return {
		'fieldname': 'expense_entry_name',
		'transactions': [
			{
				'label': _('Vouchers'),
				'items': ['Journal Entry', 'Payment Entry']
			}
		]
	}
