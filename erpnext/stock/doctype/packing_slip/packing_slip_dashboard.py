# import frappe
from frappe import _


def get_data():
	return {
		'fieldname': 'packing_slip',
		'internal_links': {
			'Sales Order': ['items', 'sales_order'],
			'Work Order': ['items', 'work_order'],
		},
		'non_standard_fieldnames': {
			'Packing Slip': 'source_packing_slip',
		},
		'transactions': [
			{
				'label': _('Fulfilment'),
				'items': ['Delivery Note', 'Sales Invoice', 'Stock Entry']
			},
			{
				'label': _('Previous Documents'),
				'items': ['Sales Order', 'Work Order']
			},
			{
				'label': _('Nested Into'),
				'items': ['Packing Slip']
			},
		]
	}
