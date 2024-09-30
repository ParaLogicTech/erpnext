from frappe import _


def get_data():
	return {
		'fieldname': 'customer_group',
		'transactions': [
			{
				'label': _('Customers'),
				'items': ['Customer']
			},
		]
	}
