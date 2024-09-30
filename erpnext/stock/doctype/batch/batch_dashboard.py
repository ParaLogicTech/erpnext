
import frappe
from frappe import _


def get_data():
	return {
		'fieldname': 'batch_no',
		'transactions': [
			{
				'label': _('Stock'),
				'items': ['Stock Entry', 'Stock Reconciliation', 'Packing Slip']
			},
			{
				'label': _('Sales'),
				'items': ['Delivery Note', 'Sales Invoice']
			},
			{
				'label': _('Purchase'),
				'items': ['Purchase Receipt', 'Purchase Invoice']
			},
		]
	}
