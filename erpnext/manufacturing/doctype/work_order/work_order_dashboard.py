from frappe import _


def get_data():
	return {
		'fieldname': 'work_order',
		'transactions': [
			{
				'label': _('Fulfilment'),
				'items': ['Stock Entry', 'Job Card']
			},
			{
				'label': _("Stock"),
				'items': ['Packing Slip', 'Pick List']
			},
			{
				'label': _("Subcontracting"),
				'items': ['Purchase Order', 'Purchase Receipt']
			},
		]
	}
