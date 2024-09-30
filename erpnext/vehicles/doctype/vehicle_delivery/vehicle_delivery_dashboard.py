from frappe import _


def get_data():
	return {
		'fieldname': 'vehicle_delivery',
		'transactions': [
			{
				'label': _('Reference'),
				'items': ['Vehicle Gate Pass']
			}
		]
	}
