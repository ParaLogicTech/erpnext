import frappe
from frappe import _

def get_data():
	common_transactions = [
		{
			'label': _("Pre Sales"),
			'items': ['Quotation', 'Supplier Quotation']
		},
		{
			'label': _("Reference"),
			'items': ['Appointment'],
		},
	]

	vehicle_domain_links = []

	disabled = {
		'fieldname': 'opportunity',
		'transactions': common_transactions
	}

	if 'Vehicles' in frappe.get_active_domains():
		enable = {
			'fieldname': 'opportunity',
			'transactions': [
				{
					'label': _('Vehicle Booking'),
					'items': ['Vehicle Quotation', 'Vehicle Booking Order']
				},
				{
					'label': _("Reference"),
					'items': ['Appointment', 'Vehicle Gate Pass'],
				},
			] + common_transactions
		}

		vehicle_domain_links.append({
			'label': _('Vehicle Booking'),
			'items': ['Vehicle Quotation', 'Vehicle Booking Order']
		})

	return disabled
