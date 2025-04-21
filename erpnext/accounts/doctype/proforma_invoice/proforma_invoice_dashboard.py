# import frappe
from frappe import _


def get_data():
	return {
		'fieldname': 'proforma_invoice',
		'non_standard_fieldnames': {
			'Journal Entry': 'reference_name',
			'Payment Entry': 'reference_name',
			'Payment Request': 'reference_name',
		},
		'internal_links': {
			'Sales Order': ['items', 'sales_order'],
			'Delivery Note': ['items', 'delivery_note'],
			'Quotation': ['items', 'quotation'],
			'Packing Slip': ['items', 'packing_slip'],
		},
		'transactions': [
			{
				'label': _('Billing'),
				'items': ['Sales Invoice', 'Payment Entry', 'Payment Request']
			},
			{
				'label': _('Previous Documents'),
				'items': ['Delivery Note', 'Sales Order', 'Quotation']
			},
			{
				'label': _('Reference'),
				'items': ['Packing Slip', 'Journal Entry']
			},
		]
	}
