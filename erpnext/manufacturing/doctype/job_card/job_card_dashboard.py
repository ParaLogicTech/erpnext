from frappe import _

def get_data():
	return {
		'fieldname': 'job_card',
		'transactions': [
			{
				'label': _('Material'),
				'items': ['Stock Entry']
			},
			{
				'label': _('Request'),
				'items': ['Material Request']
			},
		]
	}
