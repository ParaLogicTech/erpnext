from frappe import _


def get_data():
	return {
		'fieldname': 'payment_request',
		'non_standard_fieldnames': {
			'Integration Request': 'reference_docname',
		},
		'transactions': [
			{
				'label': _('Payment Gateway'),
				'items': ['Integration Request']
			},
		]
	}
