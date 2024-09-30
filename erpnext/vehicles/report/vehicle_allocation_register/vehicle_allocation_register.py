# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _, scrub, unscrub
from frappe.utils import cint, cstr, flt
from erpnext.vehicles.utils import get_booking_payments_by_order, get_advance_balance_details, get_outstanding_remarks
from erpnext.stock.report.stock_ledger.stock_ledger import get_item_group_condition
from frappe.desk.query_report import group_report_data


class VehicleAllocationRegisterReport(object):
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})

	def run(self):
		self.get_data()
		self.prepare_data()
		columns = self.get_columns()

		data = self.get_grouped_data()

		return columns, data

	def get_data(self):
		allocation_conditions = self.get_conditions('allocation')
		booking_conditions = self.get_conditions('booking')

		allocation_data = frappe.db.sql("""
			select m.name as vehicle_allocation, m.item_code, m.supplier, m.allocation_period, m.delivery_period,
				m.sr_no, m.code, m.is_additional, m.booking_price, m.vehicle_color,
				ap.from_date as allocation_from_date, dp.from_date as delivery_from_date,
				item.variant_of, item.item_group, item.brand, m.is_expired
			from `tabVehicle Allocation` m
			inner join `tabItem` item on item.name = m.item_code
			inner join `tabVehicle Allocation Period` ap on ap.name = m.allocation_period
			inner join `tabVehicle Allocation Period` dp on dp.name = m.delivery_period
			left join `tabVehicle Booking Order` vbo on m.name = vbo.vehicle_allocation and vbo.docstatus = 1
			where m.docstatus = 1 {conditions}
			order by ap.from_date, m.item_code, m.is_additional, m.sr_no
		""".format(conditions=allocation_conditions), self.filters, as_dict=1)

		self.filters.allocation_names = [d.vehicle_allocation for d in allocation_data]
		if self.filters.allocation_names:
			booking_where = "(m.vehicle_allocation in %(allocation_names)s or {0})".format(booking_conditions)
		else:
			booking_where = booking_conditions

		booking_data = frappe.db.sql("""
			select m.name as vehicle_booking_order, m.item_code, m.previous_item_code,
				m.supplier, m.allocation_period, m.delivery_period, m.vehicle_allocation, m.priority,
				m.transaction_date, m.vehicle_delivered_date, m.vehicle_received_date, m.status,
				m.color_1, m.color_2, m.color_3, m.vehicle_color, m.previous_color,
				m.customer, m.financer, m.customer_name, m.finance_type, m.tax_id, m.tax_cnic,
				m.contact_person, m.contact_mobile, m.contact_phone,
				ap.from_date as allocation_from_date, dp.from_date as delivery_from_date,
				m.invoice_total, m.vehicle_amount, m.fni_amount, m.withholding_tax_amount,
				m.customer_advance, m.supplier_advance, m.customer_advance - m.supplier_advance as undeposited_amount,
				m.payment_adjustment, m.customer_outstanding, m.supplier_outstanding,
				item.variant_of, item.item_group, item.brand,
				m.vehicle, m.vehicle_chassis_no, m.vehicle_engine_no,
				GROUP_CONCAT(DISTINCT sp.sales_person SEPARATOR ', ') as sales_person
			from `tabVehicle Booking Order` m
			inner join `tabItem` item on item.name = m.item_code
			left join `tabVehicle Allocation Period` ap on ap.name = m.allocation_period
			left join `tabVehicle Allocation Period` dp on dp.name = m.delivery_period
			left join `tabSales Team` sp on sp.parent = m.name and sp.parenttype = 'Vehicle Booking Order'
			where m.docstatus = 1 and m.vehicle_allocation_required = 1
				and {0}
			group by m.name
		""".format(booking_where), self.filters, as_dict=1)

		self.allocation_to_row = {}
		for d in allocation_data:
			self.allocation_to_row[d.vehicle_allocation] = d

		unallocated_bookings = []
		for d in booking_data:
			if d.vehicle_allocation in self.allocation_to_row:
				self.allocation_to_row[d.vehicle_allocation].update(d)
			else:
				unallocated_bookings.append(d)
				d.code = 'Unassigned'

		self.data = unallocated_bookings + allocation_data

		if self.filters.get('sales_person'):
			self.data = [d for d in self.data if d.get('sales_person')]

		return self.data

	def prepare_data(self):
		for d in self.data:
			if d.vehicle_allocation:
				d.reference_type = 'Vehicle Allocation'
				d.reference = d.vehicle_allocation or "'Unassigned'"
			else:
				d.reference_type = 'Vehicle Booking Order'
				d.reference = d.vehicle_booking_order
				d.allocation_period = None

			d.qty_delivered = 1 if d.get('vehicle_delivered_date') else 0

			d.vehicle_color = d.vehicle_color or d.color_1 or d.color_2 or d.color_3
			d.booking_color = d.color_1 or d.color_2 or d.color_3

			d.is_leased = d.financer and d.finance_type == "Leased"
			d.tax_cnic_ntn = d.tax_id or d.tax_cnic if d.is_leased else d.tax_cnic or d.tax_id
			d.contact_number = d.contact_mobile or d.contact_phone

			d.original_item_code = d.get('previous_item_code') or d.item_code

			if d.vehicle_allocation and not d.vehicle_booking_order and d.is_expired:
				d.status = "Expired"

		self.set_payment_details()

		self.data = sorted(self.data, key=lambda d: (
			bool(d.vehicle_allocation),
			cstr(d.allocation_from_date) if d.allocation_from_date else cstr(d.delivery_from_date),
			d.get('original_item_code') or d.item_code,
			cint(d.is_additional),
			d.sr_no,
			cstr(d.transaction_date)
		))

		return self.data

	def set_payment_details(self):
		booking_numbers = list(set([d.vehicle_booking_order for d in self.data if d.vehicle_booking_order]))
		self.payments_by_order = get_booking_payments_by_order(booking_numbers)

		for d in self.data:
			booking_payment_entries = self.payments_by_order.get(d.vehicle_booking_order) or []
			d.update(get_advance_balance_details(booking_payment_entries))

			d.outstanding_remarks = get_outstanding_remarks(d.customer_outstanding,
				d.vehicle_amount, d.fni_amount, d.withholding_tax_amount, d.payment_adjustment,
				is_cancelled=d.status == "Cancelled Booking", company=self.filters.get('company'))

	def get_grouped_data(self):
		data = self.data

		self.group_by = []
		for i in range(3):
			group_label = self.filters.get("group_by_" + str(i + 1), "").replace("Group by ", "")

			if not group_label:
				continue
			elif group_label == "Variant":
				group_field = "original_item_code"
			elif group_label == "Model":
				group_field = "variant_of"
			else:
				group_field = scrub(group_label)

			self.group_by.append(group_field)

		if not self.group_by:
			return data

		return group_report_data(data, self.group_by, calculate_totals=self.calculate_group_totals)

	def calculate_group_totals(self, data, group_field, group_value, grouped_by):
		totals = frappe._dict()

		# Copy grouped by into total row
		for f, g in grouped_by.items():
			totals[f] = g

		# Sum
		sum_fields = ['invoice_total', 'qty_delivered',
			'customer_advance', 'supplier_advance', 'advance_payment_amount', 'balance_payment_amount',
			'payment_adjustment', 'customer_outstanding', 'supplier_outstanding', 'undeposited_amount']
		for f in sum_fields:
			totals[f] = sum([flt(d.get(f)) for d in data])

		group_reference_doctypes = {
			"original_item_code": "Item",
			"variant_of": "Item",
			"allocation_period": "Vehicle Allocation Period",
			"delivery_period": "Vehicle Allocation Period",
		}

		reference_field = group_field[0] if isinstance(group_field, (list, tuple)) else group_field
		reference_dt = group_reference_doctypes.get(reference_field, unscrub(cstr(reference_field)))
		totals['reference_type'] = reference_dt
		totals['reference'] = grouped_by.get(reference_field)

		if reference_dt == "Vehicle Allocation Period" and not totals.get('reference'):
			totals['reference'] = "'Unassigned'"

		if "original_item_code" in grouped_by:
			totals['item_code'] = totals['original_item_code']
		elif "variant_of" in grouped_by:
			totals['item_code'] = totals['variant_of']

		count = len(data)
		booked = len([d for d in data if d.vehicle_booking_order])
		if 'allocation_period' in grouped_by and not totals.get('allocation_period'):
			totals['code'] = "Unassigned: {0}".format(count)
		else:
			totals['code'] = "Tot: {0}, Bkd: {1}, Avl: {2}".format(count, booked, count-booked)

		return totals

	def get_conditions(self, cond_type):
		conditions = []

		if self.filters.company:
			conditions.append("m.company = %(company)s")

		if self.filters.from_allocation_period:
			self.filters.allocation_from_date = frappe.get_cached_value("Vehicle Allocation Period", self.filters.from_allocation_period, "from_date")
			conditions.append("ap.from_date >= %(allocation_from_date)s")

		if self.filters.to_allocation_period:
			self.filters.allocation_to_date = frappe.get_cached_value("Vehicle Allocation Period", self.filters.to_allocation_period, "to_date")
			conditions.append("ap.to_date <= %(allocation_to_date)s")

		if self.filters.from_delivery_period:
			self.filters.delivery_from_date = frappe.get_cached_value("Vehicle Allocation Period", self.filters.from_delivery_period, "from_date")
			conditions.append("dp.from_date >= %(delivery_from_date)s")

		if self.filters.to_delivery_period:
			self.filters.delivery_to_date = frappe.get_cached_value("Vehicle Allocation Period", self.filters.to_delivery_period, "to_date")
			conditions.append("dp.to_date <= %(delivery_to_date)s")

		if self.filters.variant_of:
			conditions.append("item.variant_of = %(variant_of)s")

		if self.filters.item_code:
			if cond_type == 'booking':
				conditions.append("(m.item_code = %(item_code)s or m.previous_item_code = %(item_code)s)")
			else:
				conditions.append("(m.item_code = %(item_code)s or vbo.item_code = %(item_code)s or vbo.previous_item_code = %(item_code)s)")

		if self.filters.vehicle_color:
			if cond_type == 'booking':
				conditions.append("""(m.vehicle_color = %(vehicle_color)s or m.previous_color = %(vehicle_color)s
					or (m.color_1 = %(vehicle_color)s and ifnull(m.vehicle_color, '') = ''))""")
			else:
				conditions.append("""(m.vehicle_color = %(vehicle_color)s
					or vbo.vehicle_color = %(vehicle_color)s or vbo.previous_color = %(vehicle_color)s
					or (vbo.color_1 = %(vehicle_color)s and ifnull(vbo.vehicle_color, '') = ''))""")

		if self.filters.item_group:
			conditions.append(get_item_group_condition(self.filters.item_group))

		if self.filters.brand:
			conditions.append("item.brand = %(brand)s")

		if self.filters.vehicle:
			if cond_type == 'booking':
				conditions.append("m.vehicle = %(vehicle)s")
			else:
				conditions.append("vbo.vehicle = %(vehicle)s")

		if self.filters.customer:
			if cond_type == 'booking':
				conditions.append("m.customer = %(customer)s")
			else:
				conditions.append("vbo.customer = %(customer)s")

		if self.filters.financer:
			if cond_type == 'booking':
				conditions.append("m.financer = %(financer)s")
			else:
				conditions.append("vbo.financer = %(financer)s")

		if self.filters.supplier:
			conditions.append("m.supplier = %(supplier)s")

		if self.filters.priority:
			if cond_type == 'booking':
				conditions.append("m.priority = 1")
			else:
				conditions.append("vbo.priority = 1")

		if self.filters.get("sales_person") and cond_type == 'booking':
			lft, rgt = frappe.db.get_value("Sales Person", self.filters.sales_person, ["lft", "rgt"])
			conditions.append("""sp.sales_person in (select name from `tabSales Person`
					where lft>=%s and rgt<=%s and docstatus<2)""" % (lft, rgt))

		out = " and ".join(conditions)
		if cond_type != "booking":
			out = "and {}".format(out) if conditions else ""

		return out

	def get_columns(self):
		return [
			{"label": _("Reference"), "fieldname": "reference", "fieldtype": "Dynamic Link", "options": "reference_type", "width": 165},
			{"label": _("Sr #"), "fieldname": "sr_no", "fieldtype": "Int", "width": 45},
			{"label": _("Allocation Code"), "fieldname": "code", "fieldtype": "Data", "width": 160},
			{"label": _("Additional"), "fieldname": "is_additional", "fieldtype": "Check", "width": 55},
			{"label": _("Delivered"), "fieldname": "qty_delivered", "fieldtype": "Int", "width": 75},
			{"label": _("Allocation Period"), "fieldname": "allocation_period", "fieldtype": "Link", "options": "Vehicle Allocation Period", "width": 120},
			{"label": _("Delivery Period"), "fieldname": "delivery_period", "fieldtype": "Link", "options": "Vehicle Allocation Period", "width": 110},
			{"label": _("Variant Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 120},
			{"label": _("Color"), "fieldname": "vehicle_color", "fieldtype": "Link", "options": "Vehicle Color", "width": 120},
			{"label": _("Booking #"), "fieldname": "vehicle_booking_order", "fieldtype": "Link", "options": "Vehicle Booking Order", "width": 105},
			{"label": _("Customer Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 200},
			# {"label": _("Customer (User)"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 100},
			# {"label": _("Financer"), "fieldname": "financer", "fieldtype": "Link", "options": "Customer", "width": 100},
			{"label": _("CNIC/NTN"), "fieldname": "tax_cnic_ntn", "fieldtype": "Data", "width": 110},
			{"label": _("Contact"), "fieldname": "contact_number", "fieldtype": "Data", "width": 110},
			{"label": _("Booking Date"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 100},
			{"label": _("Received Date"), "fieldname": "vehicle_received_date", "fieldtype": "Date", "width": 100},
			{"label": _("Delivery Date"), "fieldname": "vehicle_delivered_date", "fieldtype": "Date", "width": 100},
			{"label": _("Sales Person"), "fieldtype": "Data", "fieldname": "sales_person", "width": 150},
			{"label": _("Chassis No"), "fieldname": "vehicle_chassis_no", "fieldtype": "Data", "width": 150},
			{"label": _("Engine No"), "fieldname": "vehicle_engine_no", "fieldtype": "Data", "width": 115},
			{"label": _("Vehicle"), "fieldname": "vehicle", "fieldtype": "Link", "options": "Vehicle", "width": 100},
			{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 140},
			{"label": _("Invoice Total"), "fieldname": "invoice_total", "fieldtype": "Currency", "width": 120},
			{"label": _("Payment Received"), "fieldname": "customer_advance", "fieldtype": "Currency", "width": 120},
			{"label": _("Payment Deposited"), "fieldname": "supplier_advance", "fieldtype": "Currency", "width": 120},
			{"label": _("Undeposited Amount"), "fieldname": "undeposited_amount", "fieldtype": "Currency", "width": 120},
			{"label": _("Payment Adjustment"), "fieldname": "payment_adjustment", "fieldtype": "Currency", "width": 120},
			{"label": _("Customer Outstanding"), "fieldname": "customer_outstanding", "fieldtype": "Currency", "width": 120},
			{"label": _("Supplier Outstanding"), "fieldname": "supplier_outstanding", "fieldtype": "Currency", "width": 120},
			{"label": _("Advance Payment Date"), "fieldname": "advance_payment_date", "fieldtype": "Date", "width": 100},
			{"label": _("Advance Payment Amount"), "fieldname": "advance_payment_amount", "fieldtype": "Currency", "width": 120},
			{"label": _("Balance Payment Date"), "fieldname": "balance_payment_date", "fieldtype": "Date", "width": 100},
			{"label": _("Balance Payment Amount"), "fieldname": "balance_payment_amount", "fieldtype": "Currency", "width": 120},
			{"label": _("Outstanding Remarks"), "fieldname": "outstanding_remarks", "fieldtype": "Data", "width": 150},
			{"label": _("Previous Variant"), "fieldname": "previous_item_code", "fieldtype": "Link", "options": "Item", "width": 120},
			{"label": _("Previous Color"), "fieldname": "previous_color", "fieldtype": "Link", "options": "Vehicle Color", "width": 120},
			{"label": _("Booking Color"), "fieldname": "booking_color", "fieldtype": "Link", "options": "Vehicle Color", "width": 120},
			{"label": _("Booking Price"), "fieldname": "booking_price", "fieldtype": "Data", "width": 100},
			{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Data", "width": 100},
		]


def execute(filters=None):
	return VehicleAllocationRegisterReport(filters).run()
