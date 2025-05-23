from frappe import _


def get_data():
	return {
		'fieldname': 'reference_name',
		'non_standard_fieldnames': {
			'POS Closing Entry': 'document_name',
		},
		'transactions': [
			{
				'label': _('Refund Entry'),
				'items': ['Payment Entry']
			},
			{
				'label': _('POS Closing'),
				'items': ['POS Closing Entry']
			},
		]
	}
