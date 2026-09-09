import frappe
from frappe import _


def get_data():
	dn_after_delivery = frappe.get_cached_value("Selling Settings", None, 'dn_required') == 'Required after Sales Invoice'

	payment_links = ['Payment Entry', 'Journal Entry', 'Payment Request', 'POS Closing Entry']
	previous_document_links = ['Sales Order', 'Proforma Invoice']
	reference_links = ['Packing Slip', 'Quotation']

	out = {
		'fieldname': 'sales_invoice',
		'non_standard_fieldnames': {
			'Journal Entry': 'reference_name',
			'Payment Entry': 'reference_name',
			'Payment Request': 'reference_name',
			'Sales Invoice': 'return_against',
			'Auto Repeat': 'reference_document',
			'POS Closing Entry': 'document_name',
		},
		'internal_links': {
			'Sales Order': ['items', 'sales_order'],
			'Quotation': ['items', 'quotation'],
			'Packing Slip': ['items', 'packing_slip'],
			'Proforma Invoice': ['items', 'proforma_invoice'],
		},
		'transactions': [
			{
				'label': _('Payment'),
				'items': payment_links
			},
			{
				'label': _('Previous Documents'),
				'items': previous_document_links
			},
			{
				'label': _('Reference'),
				'items': reference_links
			},
			{
				'label': _('Returns'),
				'items': ['Sales Invoice']
			},
		]
	}

	if dn_after_delivery:
		reference_links.insert(0, 'Delivery Note')
	else:
		previous_document_links.insert(0, 'Delivery Note')
		out['internal_links']['Delivery Note'] = ['items', 'delivery_note']

	return out
