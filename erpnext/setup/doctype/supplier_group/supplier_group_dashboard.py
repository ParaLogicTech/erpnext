from frappe import _


def get_data():
	return {
		'fieldname': 'supplier_group',
		'transactions': [
			{
				'label': _('Suppliers'),
				'items': ['Supplier']
			},
		]
	}
