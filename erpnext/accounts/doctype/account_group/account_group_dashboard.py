from frappe import _


def get_data():
	return {
		'fieldname': 'account_group',
		'transactions': [
			{
				'label': _('Used In'),
				'items': ['Account Group']
			}
		]
	}
