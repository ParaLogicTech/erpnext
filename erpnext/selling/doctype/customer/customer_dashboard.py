
import frappe
from frappe import _


def get_data():
	vehicle_domain_links = []
	vehicle_quotation = []
	if 'Vehicles' in frappe.get_active_domains():
		vehicle_quotation.append("Vehicle Quotation")
		vehicle_domain_links.append({
			'label': _('Vehicles'),
			'items': ['Vehicle Booking Order', 'Vehicle Delivery', 'Vehicle']
		})

	return {
		'heatmap': True,
		'heatmap_message': _('This is based on transactions against this Customer. See timeline below for details'),
		'fieldname': 'customer',
		'non_standard_fieldnames': {
			'Payment Entry': 'party',
			'Journal Entry': 'party',
			'Sales Invoice': 'bill_to',
			'Quotation': 'party_name',
			'Appointment': 'party_name',
			'Opportunity': 'party_name',
			'Vehicle Quotation': 'party_name',
			'Customer Feedback': 'party_name',
		},
		'dynamic_links': {
			'party_name': ['Customer', 'quotation_to']
		},
		'transactions': vehicle_domain_links + [
			{
				'label': _('Orders'),
				'items': ['Sales Order', 'Delivery Note', 'Sales Invoice']
			},
			{
				'label': _('Accounting'),
				'items': ['Payment Entry', 'Journal Entry', 'Subscription']
			},
			{
				'label': _('Pre Sales'),
				'items': vehicle_quotation + ['Quotation', 'Opportunity', 'Lead']
			},
			{
				'label': _('Events'),
				'items': ['Appointment', 'Customer Feedback']
			},
			{
				'label': _('Services'),
				'items': ['Project', 'Issue']
			},
			{
				'label': _('Pricing'),
				'items': ['Pricing Rule', 'Item Price']
			},
			{
				'label': _('Customer Provided Items'),
				'items': ['Item', 'Stock Entry']
			},
		]
	}
