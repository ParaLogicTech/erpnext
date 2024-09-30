import frappe
from frappe import _

def get_data():
	return {
		'fieldname': 'delivery_note',
		'non_standard_fieldnames': {
			'Stock Entry': 'delivery_note_no',
			'Quality Inspection': 'reference_name',
			'Auto Repeat': 'reference_document',
			'Delivery Note': 'return_against',
			'Installation Note': 'prevdoc_docname',
		},
		'internal_links': {
			'Sales Order': ['items', 'sales_order'],
			'Quotation': ['items', 'quotation'],
			'Packing Slip': ['items', 'packing_slip'],
		},
		'transactions': [
			{
				'label': _('Fulfilment'),
				'items': ['Sales Invoice', 'Delivery Trip', 'Installation Note']
			},
			{
				'label': _('Previous Documents'),
				'items': ['Sales Order', 'Quotation', 'Packing Slip']
			},
			{
				'label': _('Reference'),
				'items': ['Quality Inspection']
			},
			{
				'label': _('Returns'),
				'items': ['Delivery Note']
			},
		]
	}
