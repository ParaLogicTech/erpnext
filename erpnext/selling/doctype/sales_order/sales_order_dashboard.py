import frappe
from frappe import _

def get_data():
	return {
		'fieldname': 'sales_order',
		'non_standard_fieldnames': {
			'Journal Entry': 'original_reference_name',
			'Payment Entry': 'original_reference_name',
			'Payment Request': 'reference_name',
			'Auto Repeat': 'reference_document',
		},
		'internal_links': {
			'Quotation': ['items', 'quotation']
		},
		'transactions': [
			{
				'label': _('Fulfillment'),
				'items': ['Delivery Note', 'Sales Invoice', 'Packing Slip']
			},
			{
				'label': _('Reference'),
				'items': ['Quotation', 'Pick List']
			},
			{
				'label': _('Procurement'),
				'items': ['Material Request', 'Purchase Order', 'Work Order']
			},
			{
				'label': _('Payment'),
				'items': ['Payment Entry', 'Journal Entry', 'Payment Request']
			},
		]
	}
