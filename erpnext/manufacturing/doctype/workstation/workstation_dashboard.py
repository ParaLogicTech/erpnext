from frappe import _

def get_data():
	return {
		'fieldname': 'workstation',
		'transactions': [
			{
				'label': _('Masters'),
				'items': ['BOM', 'Routing', 'Operation']
			},
			{
				'label': _('Transactions'),
				'items': ['Work Order', 'Job Card']
			}
		]
	}
