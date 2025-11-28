# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
import erpnext
from frappe import _
from frappe.utils import flt, cint, cstr, ceil, getdate, clean_whitespace, now_datetime, comma_or
from erpnext.stock.get_item_details import get_applies_to_details, get_force_applies_to_fields
from frappe.model.naming import set_name_by_naming_series
from frappe.contacts.doctype.address.address import get_default_address
from frappe.contacts.doctype.contact.contact import get_default_contact, get_all_contact_nos
from erpnext.accounts.party import get_contact_details, get_address_display
from erpnext.controllers.status_updater import StatusUpdaterERP
from erpnext.projects.doctype.project_type.project_type import get_project_type_defaults
from erpnext.stock.doctype.item.item import convert_item_uom_for
from erpnext.projects.doctype.project_status.project_status import (
	get_auto_project_status,
	set_manual_project_status,
	get_valid_manual_project_status_names,
	is_manual_project_status,
	validate_project_status_for_transaction,
	apply_project_status_transition,
)
from frappe.core.doctype.notification_count.notification_count import get_all_notification_count
from erpnext.overrides.campaign.campaign_hooks import validate_campaign_voucher_code
from frappe.model.meta import get_field_precision
import json


class Project(StatusUpdaterERP):
	def __init__(self, *args, **kwargs):
		super(Project, self).__init__(*args, **kwargs)

		self.force_customer_fields = [
			"customer_name", "customer_group",
			"bill_to_name", "bill_to_customer_group",
			"tax_id", "tax_cnic", "tax_strn", "tax_status",
			"address_display", "contact_display", "contact_email",
			"billing_contact_display", "billing_address_display",
			"billing_contact_mobile", "billing_contact_phone", "billing_contact_email",
			"secondary_contact_display",
		]

		self.force_applies_to_fields = get_force_applies_to_fields(self.doctype)

		self.sales_data = frappe._dict()
		self.consumables_data = frappe._dict()
		self.invoices = []

	def get_feed(self):
		return '{0}: {1}'.format(_(self.status), frappe.safe_decode(self.project_name or self.name))

	def autoname(self):
		project_naming_by = frappe.defaults.get_global_default('project_naming_by')
		if project_naming_by == 'Project Name':
			self.name = self.project_name
		else:
			set_name_by_naming_series(self, 'project_number')

	def onload(self):
		self.set_onload('cant_change_fields', self.get_cant_change_fields(for_onload=True))
		self.set_onload('valid_manual_project_status_names', get_valid_manual_project_status_names(self))
		self.set_onload('is_manual_project_status', is_manual_project_status(self.project_status))
		self.set_onload('contact_nos', get_all_contact_nos('Customer', self.customer))
		self.set_onload('task_count', self.get_task_count())
		self.set_onload('notification_count', get_all_notification_count(self.doctype, self.name))

		self.sales_data = self.get_project_sales_data(get_sales_invoice=True)
		self.consumables_data = self.get_project_consumables_data()
		self.set_items_and_totals_html_onload(self.sales_data, self.consumables_data)

		self.tasks_data, self.timesheet_data = self.get_project_task_and_time_data()
		self.set_task_and_timelogs_html_onload(self.timesheet_data, self.tasks_data)

	def before_print(self, print_settings=None):
		self.company_address_doc = erpnext.get_company_address_doc(self)
		self.sales_data = self.get_project_sales_data(get_sales_invoice=True)
		self.consumables_data = self.get_project_consumables_data()
		self.tasks_data, self.timesheet_data = self.get_project_task_and_time_data()
		self.get_sales_invoice_names()

	def before_validate(self):
		pass

	def validate(self):
		self.set_service_template_has_transaction()
		if self.status not in ('Completed', 'Closed', 'Cancelled'):
			self.set_missing_values(for_validate=True)

		self.validate_appointment()
		self.validate_phone_nos()
		self.validate_project_type()
		self.validate_cash_billing()
		self.validate_depreciation()
		self.validate_warranty()
		self.validate_campaign()

		self.set_title()

		self.set_tasks_status()
		self.set_percent_complete()
		self.set_project_date()
		self.set_advance_received_amount()
		self.set_billing_and_delivery_status()
		self.set_procurement_status()
		self.set_costing()
		self.run_method("set_additional_status")
		self.set_status(from_doctype=self.doctype, action=self.get("_action"))

		self.validate_cant_change()

		self._previous_appointment = self.db_get('appointment')

	def on_update(self):
		self.update_appointment()
		self.handle_on_status_change()

	def handle_on_status_change(self):
		if self.flags.status_changed:
			self.run_method("on_status_change")
			self.flags.status_changed = False

	def before_insert(self):
		self.validate_appointment_required()

	def after_insert(self):
		self.set_project_in_sales_order_and_quotation()

	def after_delete(self):
		self.update_appointment()

	def on_status_change(self):
		pass

	def set_additional_status(self):
		pass

	def set_title(self):
		if self.project_name:
			self.title = self.project_name
		elif self.customer_name or self.customer:
			self.title = self.customer_name or self.customer
		else:
			self.title = self.name

	def set_billing_and_delivery_status(self, update=False, update_modified=False):
		sales_data = self.get_project_sales_data(get_sales_invoice=False)
		self.total_billable_amount = sales_data.totals.grand_total
		self.customer_billable_amount = sales_data.totals.customer_grand_total

		self.additional_insurance_excess_amount = flt(
			sales_data.totals.insurance_net_total * flt(self.insurance_excess_percentage) / 100,
			self.precision("additional_insurance_excess_amount")
		)

		self.total_billed_amount = self.get_billed_amount()

		sales_orders = frappe.get_all(
			"Sales Order",
			fields=['billing_status', 'delivery_status', 'status', 'skip_delivery_note', 'transaction_date'],
			filters={
				"project": self.name, "docstatus": 1
			},
			order_by="transaction_date, creation"
		)

		delivery_notes = frappe.get_all("Delivery Note", fields=['billing_status', 'status'], filters={
			"project": self.name, "docstatus": 1, "is_return": 0,
		})

		has_unbilled_standalone_proforma = frappe.db.sql("""
			select p.name
			from `tabProforma Invoice Item` i
			inner join `tabProforma Invoice` p on p.name = i.parent
			where p.docstatus = 1
				and p.project = %s
				and p.status != 'Closed'
				and abs(i.billed_qty) < abs(i.qty)
				and ifnull(i.delivery_note, '') = ''
				and ifnull(i.sales_order, '') = ''
			limit 1
		""", self.name)

		material_requests = frappe.get_all("Material Request", fields=['receipt_status', 'status', 'per_received'], filters={
			"project": self.name, "docstatus": 1, "material_request_type": "Material Issue",
		})

		sales_invoices = self.get_sales_invoices()

		self.billing_status, self.to_bill = self.get_billing_status(sales_orders, delivery_notes, sales_invoices, has_unbilled_standalone_proforma, self.total_billed_amount)
		self.delivery_status, self.to_deliver = self.get_delivery_status(sales_orders, delivery_notes, material_requests)

		self.first_sales_order_date = sales_orders[0].transaction_date if sales_orders else None

		self.final_invoice_date = None
		if sales_invoices and self.billing_status == "Fully Billed":
			self.final_invoice_date = sales_invoices[-1].posting_date

		if update:
			self.db_set({
				'total_billable_amount': self.total_billable_amount,
				'customer_billable_amount': self.customer_billable_amount,
				'additional_insurance_excess_amount': self.additional_insurance_excess_amount,
				'total_billed_amount': self.total_billed_amount,
				'billing_status': self.billing_status,
				'to_bill': self.to_bill,
				'delivery_status': self.delivery_status,
				'to_deliver': self.to_deliver,
				'final_invoice_date': self.final_invoice_date,
				'first_sales_order_date': self.first_sales_order_date,
			}, None, update_modified=update_modified)

	def get_billing_status(self, sales_orders, delivery_notes, sales_invoices, has_unbilled_standalone_proforma, total_billed_amount):
		has_billables = False
		has_unbilled = False
		has_sales_invoice = False

		for d in sales_orders + delivery_notes:
			if d.status != "Closed":
				has_billables = True
				if d.billing_status == "To Bill":
					has_unbilled = True

		if has_unbilled_standalone_proforma:
			has_billables = True
			has_unbilled = True

		if self.insurance_excess_amount or self.additional_insurance_excess_amount:
			positive_excess, negative_excess = self.get_insurance_excess_billed()
			precision = self.precision("insurance_excess_amount")
			if negative_excess and negative_excess - positive_excess > 1 / 10 ** precision:
				has_unbilled = True

		if sales_invoices:
			has_sales_invoice = True

		if has_billables:
			if has_sales_invoice:
				if has_unbilled:
					if flt(total_billed_amount) > 0:
						billing_status = "Partly Billed"
						to_bill = 1
					else:
						billing_status = "Not Billed"
						to_bill = 1
				else:
					billing_status = "Fully Billed"
					to_bill = 0
			else:
				billing_status = "Not Billed"
				to_bill = 1
		else:
			if has_sales_invoice:
				billing_status = "Fully Billed"
				to_bill = 0
			else:
				billing_status = "Not Applicable"
				to_bill = 0

		return billing_status, to_bill

	def get_delivery_status(self, sales_orders, delivery_notes, material_requests):
		has_deliverables = False
		has_undelivered = False
		has_delivery = False

		if delivery_notes:
			has_delivery = True

		for d in sales_orders:
			if not d.skip_delivery_note:
				if d.delivery_status in ("To Deliver", "Delivered"):
					has_deliverables = True
				if d.delivery_status == "To Deliver":
					has_undelivered = True

		for d in material_requests:
			if d.receipt_status in ("To Receive", "Received"):
				has_deliverables = True
			if d.receipt_status == "To Receive":
				has_undelivered = True
			if d.per_received > 0:
				has_delivery = True

		if has_deliverables:
			if has_delivery:
				if has_undelivered:
					delivery_status = "Partly Delivered"
					to_deliver = 1
				else:
					delivery_status = "Fully Delivered"
					to_deliver = 0
			else:
				delivery_status = "Not Delivered"
				to_deliver = 1
		else:
			if has_delivery:
				delivery_status = "Fully Delivered"
				to_deliver = 0
			else:
				delivery_status = "Not Applicable"
				to_deliver = 0

		return delivery_status, to_deliver

	def set_procurement_status(self, update=False, update_modified=False):
		status_data = self.get_procurement_status()

		self.procurement_status = status_data.procurement_status
		self.to_receive_materials = status_data.to_receive_materials
		self.last_purchase_order_date = status_data.last_purchase_order_date
		self.last_purchase_receipt_date = status_data.last_purchase_receipt_date
		self.last_material_request_date = status_data.last_material_request_date

		if update:
			self.db_set({
				'procurement_status': self.procurement_status,
				'to_receive_materials': self.to_receive_materials,
				'last_purchase_order_date': self.last_purchase_order_date,
				'last_purchase_receipt_date': self.last_purchase_receipt_date,
				'last_material_request_date': self.last_material_request_date,
			}, None, update_modified=update_modified)

	def get_procurement_status(self):
		purchase_orders = frappe.db.sql("""
			select p.receipt_status, p.status, i.qty, i.received_qty, p.transaction_date
			from `tabPurchase Order Item` i
			inner join `tabPurchase Order` p on p.name = i.parent
			where p.docstatus = 1 and i.project = %s and i.is_stock_item = 1 
			order by p.transaction_date, p.creation
		""", self.name, as_dict=1)

		purchase_receipts = frappe.db.sql("""
			select p.status, i.qty, i.received_qty, p.posting_date
			from `tabPurchase Receipt Item` i
			inner join `tabPurchase Receipt` p on p.name = i.parent
			where p.docstatus = 1 and i.project = %s and i.is_stock_item = 1 
			order by p.posting_date, p.creation
		""", self.name, as_dict=1)

		material_requests = frappe.get_all(
			"Material Request",
			fields=['receipt_status', 'status', 'per_received', 'transaction_date'],
			filters={
				"project": self.name,
				"docstatus": 1,
				"material_request_type": ["in", ["Purchase", "Material Transfer", "Customer Provided"]],
			},
			order_by="transaction_date, creation",
		)

		last_purchase_order_date = purchase_orders[-1].transaction_date if purchase_orders else None
		last_purchase_receipt_date = purchase_receipts[-1].posting_date if purchase_receipts else None
		last_material_request_date = material_requests[-1].transaction_date if material_requests else None

		has_receivables = False
		has_unreceived = False
		has_receipt = False

		if purchase_receipts:
			has_receipt = True

		for d in purchase_orders:
			if d.receipt_status in ("To Receive", "Received"):
				has_receivables = True
			if flt(d.received_qty) < flt(d.qty) and d.receipt_status == "To Receive":
				has_unreceived = True

		for d in material_requests:
			if d.receipt_status in ("To Receive", "Received"):
				has_receivables = True
			if d.receipt_status == "To Receive":
				has_unreceived = True
			if d.per_received > 0:
				has_receipt = True

		if has_receivables:
			if has_receipt:
				if has_unreceived:
					procurement_status = "Partly Received"
					to_receive = 1
				else:
					procurement_status = "Fully Received"
					to_receive = 0
			else:
				procurement_status = "Not Received"
				to_receive = 1
		else:
			if has_receipt:
				procurement_status = "Fully Received"
				to_receive = 0
			else:
				procurement_status = "Not Applicable"
				to_receive = 0

		return frappe._dict({
			"procurement_status": procurement_status,
			"to_receive_materials": to_receive,
			"last_purchase_order_date": last_purchase_order_date,
			"last_purchase_receipt_date": last_purchase_receipt_date,
			"last_material_request_date": last_material_request_date,
		})

	def get_billed_amount(self):
		directly_billed = frappe.db.sql("""
			select sum(base_grand_total)
			from `tabSales Invoice`
			where project = %s and docstatus = 1
		""", self.name)
		directly_billed = flt(directly_billed[0][0]) if directly_billed else 0

		indirectly_billed = frappe.db.sql("""
			select sum(i.base_tax_inclusive_amount)
			from `tabSales Invoice Item` i
			inner join `tabSales Invoice` p on p.name = i.parent
			where i.project = %(project)s and ifnull(p.project, '') != %(project)s and p.docstatus = 1
		""", {'project': self.name})
		indirectly_billed = flt(indirectly_billed[0][0]) if indirectly_billed else 0

		grand_total_precision = get_field_precision(frappe.get_meta("Sales Invoice").get_field("grand_total"),
			currency=frappe.get_cached_value('Company', self.company, "default_currency"))
		return flt(directly_billed + indirectly_billed, grand_total_precision)

	def set_advance_received_amount(self, update=False, update_modified=False):
		payment_entries = self.get_advance_payment_entries()
		self.advance_received_amount = sum([d.total_amount for d in payment_entries])

		if update:
			self.db_set({
				"advance_received_amount": self.advance_received_amount
			}, update_modified=update_modified)

	def get_advance_payment_entries(self, customer=None):
		payment_entries = []

		customers = []
		if customer:
			customers.append(customer)
		else:
			if self.customer:
				customers.append(self.customer)
			if self.bill_to and self.bill_to != self.customer:
				customers.append(self.bill_to)

		if customers and not self.is_new():
			payment_entries = frappe.db.sql("""
				select
					pe.name,
					pe.payment_type,
					pe.unallocated_amount,
					if(
						pe.payment_type = 'Receive',
						pe.base_paid_amount_after_tax,
						-1 * pe.base_received_amount_after_tax
					) as total_amount
				from `tabPayment Entry` pe
				where pe.docstatus = 1
					and pe.project = %(project)s
					and pe.party_type = 'Customer'
					and pe.party in %(customers)s
					and not exists(
						select pref.name
						from `tabPayment Entry Reference` pref
						where pref.parent = pe.name and ifnull(pref.original_reference_doctype, '') not in ('', 'Sales Order', 'Proforma Invoice', 'Payment Entry')
					)
			""", {
				"customers": customers,
				"project": self.name,
			}, as_dict=1)

		return payment_entries

	def set_service_template_has_transaction(self, update=False, update_modified=False):
		ordered_set = []
		requested_set = []
		warranty_set = []
		if not self.is_new():
			ordered_set = get_service_template_ordered_set(self)
			requested_set = get_service_template_requested_set(self)
			warranty_set = get_service_template_warranty_set(self)

		for d in self.service_templates:
			d.has_sales_order = cint(bool(d.name in ordered_set))
			d.has_material_request = cint(bool(d.name in requested_set))
			d.has_service_warranty = cint(bool(d.name in warranty_set))

			if update:
				d.db_set({
					"has_sales_order": d.has_sales_order,
					"has_material_request": d.has_material_request,
					"has_service_warranty": d.has_service_warranty,
				}, update_modified=update_modified)

	def set_costing(self, update=False, update_modified=False):
		self.set_sales_amount(update=update, update_modified=update_modified)
		self.set_pending_quotation_amount(update=update, update_modified=update_modified)
		self.set_timesheet_values(update=update, update_modified=update_modified)
		self.set_expense_claim_values(update=update, update_modified=update_modified)
		self.set_purchase_values(update=update, update_modified=update_modified)
		self.set_material_consumed_cost(update=update, update_modified=update_modified)
		self.set_material_cost_of_sales(update=update, update_modified=update_modified)
		self.set_gross_margin(update=update, update_modified=update_modified)

	def set_sales_amount(self, update=False, update_modified=False):
		sales_data = self.get_project_sales_data(get_sales_invoice=True)
		self.total_sales_amount = sales_data.totals.net_total
		self.material_sales_amount = sales_data.material_items.net_total
		self.part_sales_amount = sales_data.part_items.net_total
		self.lubricant_sales_amount = sales_data.lubricant_items.net_total
		self.consumable_sales_amount = sales_data.consumable_items.net_total
		self.paint_sales_amount = sales_data.paint_items.net_total
		self.service_sales_amount = sales_data.service_items.net_total
		self.labour_sales_amount = sales_data.labour_items.net_total
		self.hourly_labour_sales_amount = sales_data.hourly_labour_items.net_total
		self.package_sales_amount = sales_data.package_items.net_total
		self.sublet_sales_amount = sales_data.sublet_items.net_total
		self.total_discount_amount = sales_data.totals.total_discount
		self.sold_time = sales_data.sold_time

		if update:
			self.db_set({
				'total_sales_amount': self.total_sales_amount,
				'material_sales_amount': self.material_sales_amount,
				'part_sales_amount': self.part_sales_amount,
				'lubricant_sales_amount': self.lubricant_sales_amount,
				'consumable_sales_amount': self.consumable_sales_amount,
				'paint_sales_amount': self.paint_sales_amount,
				'service_sales_amount': self.service_sales_amount,
				'labour_sales_amount': self.labour_sales_amount,
				'hourly_labour_sales_amount': self.hourly_labour_sales_amount,
				'package_sales_amount': self.package_sales_amount,
				'sublet_sales_amount': self.sublet_sales_amount,
				'total_discount_amount': self.total_discount_amount,
				'sold_time': self.sold_time,
			}, None, update_modified=update_modified)

	def set_timesheet_values(self, update=False, update_modified=False):
		time_sheet_data = frappe.db.sql("""
			select
				sum(costing_amount) as costing_amount,
				sum(billing_amount) as billing_amount,
				min(from_time) as from_time,
				max(to_time) as to_time,
				sum(hours) as time
			from `tabTimesheet Detail`
			where project = %s and docstatus < 2
		""", self.name, as_dict=1)[0]

		self.actual_start_date = time_sheet_data.from_time
		self.actual_end_date = time_sheet_data.to_time if self.ready_to_close else None

		self.timesheet_costing_amount = flt(time_sheet_data.costing_amount)
		self.timesheet_billable_amount = flt(time_sheet_data.billing_amount)
		self.actual_time = flt(time_sheet_data.time)

		if update:
			self.db_set({
				'actual_start_date': self.actual_start_date,
				'actual_end_date': self.actual_end_date,
				'timesheet_costing_amount': self.timesheet_costing_amount,
				'timesheet_billable_amount': self.timesheet_billable_amount,
				'actual_time': self.actual_time,
			}, None, update_modified=update_modified)

	def set_expense_claim_values(self, update=False, update_modified=False):
		expense_claim_data = frappe.db.sql("""
			select sum(sanctioned_amount) as total_sanctioned_amount
			from `tabExpense Claim Detail`
			where project = %s and docstatus = 1
		""", self.name, as_dict=1)[0]

		self.total_expense_claim = flt(expense_claim_data.total_sanctioned_amount)

		if update:
			self.db_set({
				'total_expense_claim': self.total_expense_claim,
			}, None, update_modified=update_modified)

	def set_purchase_values(self, update=False, update_modified=False):
		purchase_receipt_cost = frappe.db.sql("""
			select sum(base_net_amount * (qty - billed_qty) / qty)
			from `tabPurchase Receipt Item`
			where docstatus = 1 and project = %s and is_stock_item = 0 and is_fixed_asset = 0 and billed_qty < qty
		""", self.name)
		purchase_receipt_cost = flt(purchase_receipt_cost[0][0]) if purchase_receipt_cost else 0

		purchase_invoice_cost = frappe.db.sql("""
			select sum(base_net_amount)
			from `tabPurchase Invoice Item`
			where docstatus = 1 and project = %s and is_stock_item = 0 and is_fixed_asset = 0
		""", self.name)
		purchase_invoice_cost = flt(purchase_invoice_cost[0][0]) if purchase_invoice_cost else 0

		self.total_purchase_cost = purchase_receipt_cost + purchase_invoice_cost

		if update:
			self.db_set({
				'total_purchase_cost': self.total_purchase_cost,
			}, None, update_modified=update_modified)

	def set_material_consumed_cost(self, update=False, update_modified=False):
		amount = frappe.db.sql("""
			select sum(if(se.purpose = 'Material Issue', sed.amount, -sed.amount))
			from `tabStock Entry Detail` sed
			inner join `tabStock Entry` se on sed.parent = se.name
			where se.docstatus = 1 and se.project = %s and se.purpose in ('Material Issue', 'Material Receipt')
		""", self.name, as_list=1)

		amount = flt(amount[0][0]) if amount else 0

		self.total_consumed_material_cost = amount

		if update:
			self.db_set({
				'total_consumed_material_cost': self.total_consumed_material_cost,
			}, None, update_modified=update_modified)

	def set_material_cost_of_sales(self, update=False, update_modified=False):
		amount = frappe.db.sql("""
			select -sum(stock_value_difference)
			from `tabStock Ledger Entry` sle
			where sle.project = %s and sle.voucher_type in ('Delivery Note', 'Sales Invoice')
		""", self.name, as_list=1)

		amount = flt(amount[0][0]) if amount else 0

		self.material_cost_of_sales = amount

		if update:
			self.db_set({
				'material_cost_of_sales': self.material_cost_of_sales,
			}, None, update_modified=update_modified)

	def set_gross_margin(self, update=False, update_modified=False):
		total_revenue = flt(self.total_sales_amount, 9)
		total_expense = flt(
			flt(self.timesheet_costing_amount)
			+ flt(self.total_expense_claim)
			+ flt(self.total_purchase_cost)
			+ flt(self.total_consumed_material_cost)
			+ flt(self.material_cost_of_sales), 9)

		self.gross_margin = flt(total_revenue - total_expense, 9)
		self.per_gross_margin = flt(self.gross_margin / total_revenue, 6) * 100 if total_revenue else 0

		if update:
			self.db_set({
				'gross_margin': self.gross_margin,
				'per_gross_margin': self.per_gross_margin,
			}, None, update_modified=update_modified)

	def set_tasks_status(self, update=False, update_modified=False):
		tasks_data = frappe.get_all(
			"Task",
			fields=["name", "status", "assigned_to", "task_type"],
			filters={
				"project": self.name,
				"status": ["!=", "Cancelled"],
			},
			order_by="creation asc",
		)

		self.current_task_type = None

		if not tasks_data:
			self.tasks_status = "No Tasks"
		elif all(d.status == "Completed" for d in tasks_data):
			self.tasks_status = "Completed"
		elif current_tasks := [d for d in tasks_data if d.status == "Working"]:
			self.tasks_status = "In Progress"
			self.current_task_type = current_tasks[0].task_type
		elif current_tasks := [d for d in tasks_data if d.status == "On Hold"]:
			self.tasks_status = "On Hold"
			self.current_task_type = current_tasks[0].task_type
		elif current_tasks := [d for d in tasks_data if d.status == "Open" and d.assigned_to]:
			self.tasks_status = "Assigned"
			self.current_task_type = current_tasks[0].task_type
		else:
			self.tasks_status = "To Assign"

		if update:
			self.db_set({
				"tasks_status": self.tasks_status,
				"current_task_type": self.current_task_type,
			}, update_modified=update_modified)

	def get_task_count(self):
		tasks_data = frappe.get_all("Task", pluck="status", filters={
			"project": self.name,
			"status": ["!=", "Cancelled"],
		})

		count = frappe._dict({
			"total_tasks": len(tasks_data),
			"completed_tasks": len([status for status in tasks_data if status == "Completed"]),
		})

		return count

	def set_percent_complete(self, update=False, update_modified=False):
		if self.percent_complete_method == "Manual":
			if self.status == "Completed":
				self.percent_complete = 100
			return

		total = frappe.db.count('Task', dict(project=self.name))

		if not total:
			self.percent_complete = 0
		else:
			if (self.percent_complete_method == "Task Completion" and total > 0) or (not self.percent_complete_method and total > 0):
				completed = frappe.db.sql("""
					select count(name)
					from tabTask where
					project=%s and status in ('Cancelled', 'Completed')
				""", self.name)[0][0]
				self.percent_complete = flt(flt(completed) / total * 100, 2)

			if self.percent_complete_method == "Task Progress" and total > 0:
				progress = frappe.db.sql("""select sum(progress) from tabTask where project=%s""", self.name)[0][0]
				self.percent_complete = flt(flt(progress) / total, 2)

			if self.percent_complete_method == "Task Weight" and total > 0:
				weight_sum = frappe.db.sql("""select sum(task_weight) from tabTask where project=%s""", self.name)[0][0]
				weighted_progress = frappe.db.sql("""select progress, task_weight from tabTask where project=%s""", self.name, as_dict=1)
				pct_complete = 0
				for row in weighted_progress:
					pct_complete += row["progress"] * frappe.utils.safe_div(row["task_weight"], weight_sum)
				self.percent_complete = flt(flt(pct_complete), 2)

		if update:
			self.db_set({
				'percent_complete': self.percent_complete,
			}, None, update_modified=update_modified)

	def set_ready_to_close(self, update=True, validate=True):
		previous_ready_to_close = cint(self.db_get("ready_to_close")) if not self.is_new() else 0
		self.ready_to_close = 1

		if validate:
			self.validate_on_ready_to_close()

		if not previous_ready_to_close:
			self.ready_to_close_dt = now_datetime()

		if update:
			self.db_set({
				'ready_to_close': self.ready_to_close,
				'ready_to_close_dt': self.ready_to_close_dt,
			}, None)

		if self.ready_to_close != previous_ready_to_close:
			self.flags.status_changed = True

	def validate_on_ready_to_close(self):
		self.check_sales_order_on_ready_to_close()
		self.check_incomplete_tasks()
		self.check_pending_material_requests()
		self.check_undelivered_sales_orders()
		self.check_unordered_service_templates()
		self.check_insurance_details_on_ready_to_close()
		self.check_margin_on_ready_to_close()

	def check_sales_order_on_ready_to_close(self):
		if not frappe.get_cached_value("Projects Settings", None, "validate_sales_order_mandatory"):
			return

		if not frappe.db.exists("Sales Order", {"project": self.name, "docstatus": 1}):
			frappe.throw(_("Sales Order is mandatory before setting as Ready to Close"))

	def check_incomplete_tasks(self):
		incomplete_tasks = frappe.get_all("Task", filters={
			"project": self.name,
			"status": ["not in", ["Completed", "Cancelled"]]
		}, fields=["name", "subject"])

		if incomplete_tasks:
			frappe.throw(_("Task not completed:<br><br><ul>{0}</ul>").format(
				"".join([f"<li>{frappe.utils.get_link_to_form('Task', d.name)} ({d.subject})</li>" for d in incomplete_tasks])
			))

	def check_unordered_service_templates(self):
		validate_service_template_sales_order = frappe.get_cached_value("Projects Settings", None, "validate_service_template_sales_order")
		if not validate_service_template_sales_order:
			return

		for d in self.service_templates:
			if d.has_sales_order or not d.service_template:
				continue

			requires_sales_order = False
			template_doc = frappe.get_cached_doc("Service Template", d.service_template)
			if template_doc.sales_items:
				requires_sales_order = True

			if requires_sales_order:
				frappe.throw(_("Row #{0}: Please create Sales Order for Service Template {1}: {2}").format(
					d.idx, frappe.bold(d.service_template), d.service_template_name
				))

	def check_pending_material_requests(self):
		pending_material_requests = frappe.get_all("Material Request", filters={
			"project": self.name,
			"docstatus": 1,
			"receipt_status": "To Receive",
			"status": ["!=", "Stopped"],
		}, pluck="name")

		if pending_material_requests:
			pending_mreq_txt = [frappe.utils.get_link_to_form("Material Request", mreq) for mreq in pending_material_requests]
			pending_mreq_txt = ", ".join(pending_mreq_txt)
			if pending_mreq_txt:
				pending_mreq_txt = "<br><br>" + pending_mreq_txt

			frappe.throw(_("{0} has pending Material Requests.{1}").format(
				frappe.get_desk_link("Project", self.name), pending_mreq_txt
			), title=_("Pending Material Requests"))

	def check_insurance_details_on_ready_to_close(self):
		if self.get('insurance_company') and not self.get('insurance_loss_no'):
			frappe.throw(_("{0} is missing").format(self.meta.get_label("insurance_loss_no")))

	def check_margin_on_ready_to_close(self):
		validate_gross_margin = cint(frappe.get_cached_value("Projects Settings", None, "validate_gross_margin"))
		validate_labour_margin = cint(frappe.get_cached_value("Projects Settings", None, "validate_labour_margin"))
		if not validate_gross_margin and not validate_labour_margin:
			return

		margin_validation_override_role = frappe.get_cached_value("Projects Settings", None, "margin_validation_override_role")
		if margin_validation_override_role:
			if margin_validation_override_role in frappe.get_roles():
				return

		self.set_costing(update=True)

		if validate_gross_margin:
			if flt(self.gross_margin, self.precision("gross_margin")) < 0:
				frappe.throw(_("Gross Margin is negative, please check sales and costing amount before closing"))

		if validate_labour_margin:
			labour_margin = flt(self.labour_sales_amount) - flt(self.timesheet_costing_amount)
			if flt(labour_margin, self.precision("gross_margin")) < 0:
				frappe.throw(_("Labour Margin is negative, please check sales and costing amount before closing"))

	def reopen_status(self, update=True):
		self.ready_to_close = 0
		self.ready_to_close_dt = None

		if update:
			self.db_set({
				'ready_to_close': self.ready_to_close,
				'ready_to_close_dt': self.ready_to_close_dt,
			}, None)

	def validate_for_transaction(self, doc):
		if doc.doctype in ("Sales Invoice", "Proforma Invoice"):
			if not self.is_insurance_excess_invoice_for_customer(doc):
				if doc.doctype == "Sales Invoice" or doc.docstatus == 1:
					self.check_is_ready_to_close()
				self.check_undelivered_sales_orders()

		if doc.doctype in ("Payment Entry", "Payment Request"):
			self.validate_payment_customer(doc)

		if doc.doctype == "Service Warranty":
			self.check_is_ready_to_close()

	def check_is_ready_to_close(self):
		if not frappe.get_cached_value("Projects Settings", None, "validate_ready_to_close"):
			return

		if not self.ready_to_close:
			frappe.throw(_("{0} is not Ready to Close").format(frappe.get_desk_link(self.doctype, self.name)))

	def check_undelivered_sales_orders(self):
		if cint(self.get('allow_billing_undelivered_sales_orders')):
			return

		undelivered_sales_orders = frappe.get_all("Sales Order", filters={
			"project": self.name,
			"docstatus": 1,
			"delivery_status": "To Deliver",
			"status": ["!=", "Closed"],
		}, pluck="name")

		if undelivered_sales_orders:
			pending_so_txt = [frappe.utils.get_link_to_form("Sales Order", so) for so in undelivered_sales_orders]
			pending_so_txt = ", ".join(pending_so_txt)
			if pending_so_txt:
				pending_so_txt = "<br><br>" + pending_so_txt

			frappe.throw(_("{0} has Sales Orders with undelivered stock items. ").format(
				frappe.get_desk_link("Project", self.name), pending_so_txt
			), title=_("Undelivered Sales Orders"))

	def validate_payment_customer(self, doc):
		allowed_customers = [self.customer, self.bill_to]
		allowed_customers = list(set([c for c in allowed_customers if c]))
		if allowed_customers and doc.party_type == "Customer" and doc.party not in allowed_customers:
			frappe.throw(_("Payment Customer does not match with {0}. Customer must be {1}").format(
				frappe.get_desk_link("Project", self.name), comma_or(allowed_customers)
			))

	def is_insurance_excess_invoice_for_customer(self, doc):
		if doc.doctype not in ("Sales Invoice", "Proforma Invoice"):
			return False

		insurance_excess_item = frappe.get_cached_value("Projects Settings", None, "insurance_excess_item")
		if not insurance_excess_item:
			return False

		billed_to = doc.bill_to or doc.customer
		if billed_to != self.customer:
			return False

		return doc.items and all(d.item_code == insurance_excess_item for d in doc.items)

	def check_po_no_is_set(self, doc):
		if self.po_no or doc.is_pos:
			return

		check_po_no = frappe.get_cached_value("Projects Settings", None, "validate_po_for_billing_company_customer")
		if not check_po_no:
			return

		project_billing_customer = self.bill_to or self.customer
		invoice_billing_customer = doc.get("bill_to") or doc.get("customer")

		if project_billing_customer == invoice_billing_customer:
			customer_type = frappe.get_cached_value("Customer", invoice_billing_customer, "customer_type")
			if customer_type == "Company":
				frappe.throw(_("Please set Customer's PO No in {0} for billing against Company Customer").format(
					frappe.get_desk_link("Project", self.name)
				))

	def validate_project_status_for_transaction(self, doc):
		validate_project_status_for_transaction(self, doc)

	def set_status(
		self,
		update=False,
		status=None,
		update_modified=True,
		reset=False,
		from_doctype=None,
		action=None,
	):
		if self.is_new():
			self.flags.previous_status, self.flags.previous_project_status, self.flags.previous_indicator_color = (
				self.status, self.project_status, self.indicator_color
			)
		else:
			self.flags.previous_status, self.flags.previous_project_status, self.flags.previous_indicator_color = self.db_get([
				"status", "project_status", "indicator_color"
			])

		# set/reset manual status
		if reset:
			self.project_status = None
			self.status = status or "Open"
		elif status:
			set_manual_project_status(self, status)
		else:
			apply_project_status_transition(self, from_doctype, action)

		# get evaulated status
		project_status = get_auto_project_status(self) or frappe._dict()

		# do not set status if no auto status
		if project_status:
			self.status = project_status.status

		# set status
		self.project_status = project_status.name
		self.indicator_color = project_status.indicator_color
		self.show_task_type = cint(project_status.show_task_type)

		# status comment only if project status changed
		if not self.is_new() and self.project_status and self.project_status != self.flags.previous_project_status:
			self.add_comment("Label", _(self.project_status))

		if self.status != self.flags.previous_status:
			self.flags.status_changed = True

		# update database only if changed
		if update:
			if (
				self.project_status != self.flags.previous_project_status
				or self.status != self.flags.previous_status
				or cstr(self.indicator_color) != cstr(self.flags.previous_indicator_color)
			):
				self.db_set({
					'project_status': self.project_status,
					'status': self.status,
					'indicator_color': self.indicator_color,
					'show_task_type': self.show_task_type,
				}, None, update_modified=update_modified)

			# Only run after updating directly in db
			self.handle_on_status_change()

	def validate_cant_change(self):
		if self.is_new():
			return

		fields = self.get_cant_change_fields()
		cant_change_fields = [f for f, cant_change in fields.items() if cant_change and self.meta.get_field(f) and self.meta.get_field(f).fieldtype != 'Table']

		if cant_change_fields:
			previous_values = frappe.db.get_value(self.doctype, self.name, cant_change_fields, as_dict=1)
			for f, old_value in previous_values.items():
				if cstr(self.get(f)) != cstr(old_value):
					label = self.meta.get_label(f)
					frappe.throw(_("Cannot change {0} because transactions already exist against this Project")
						.format(frappe.bold(label)))

		self.validate_cant_change_service_template()

	def validate_cant_change_service_template(self):
		if self.is_new():
			return

		current_row_names = [d.name for d in self.service_templates]

		previous_rows = frappe.db.sql("""
			select name, service_template, service_template_name, has_sales_order, has_material_request
			from `tabProject Service Template`
			where parent = %s
		""", self.name, as_dict=1)

		previous_row_map = {}
		for prev in previous_rows:
			previous_row_map[prev.name] = prev

		# Check removed rows
		for prev in previous_rows:
			cant_change = prev.has_sales_order
			if cant_change and prev.name not in current_row_names:
				frappe.throw(_("Cannot remove Service Template <b>{0}</b>: {1} because it has a Sales Order against it").format(
					frappe.bold(prev.service_template), prev.service_template_name
				))

		# Check template changed
		for curr in self.service_templates:
			prev = previous_row_map.get(curr.name)
			if not prev:
				continue

			cant_change = prev.has_sales_order or prev.has_service_warranty
			if cant_change and curr.service_template != prev.service_template:
				frappe.throw(_("Row #{0}: Cannot change Service Template because it has transactions against it").format(
					curr.idx
				))

	def get_cant_change_fields(self, for_onload=False):
		has_sales_transaction = self.has_sales_transaction()
		has_billable_transaction = self.has_billable_transaction()

		out = frappe._dict({
			'customer': has_sales_transaction or self.advance_received_amount,
			'bill_to': self.is_warranty_claim and has_billable_transaction,
			'is_warranty_claim': self.is_warranty_claim and has_billable_transaction,
		})

		if for_onload:
			project_type_defaults = get_project_type_defaults(self.project_type)
			for field in project_type_defaults:
				out[field] = True

		return out

	def has_sales_transaction(self):
		if getattr(self, '_has_sales_transaction', None):
			return self._has_sales_transaction

		if frappe.db.get_value("Sales Order", {'project': self.name, 'docstatus': 1})\
				or frappe.db.get_value("Sales Invoice", {'project': self.name, 'docstatus': 1})\
				or frappe.db.get_value("Proforma Invoice", {'project': self.name, 'docstatus': 1})\
				or frappe.db.get_value("Delivery Note", {'project': self.name, 'docstatus': 1})\
				or frappe.db.get_value("Quotation", {'project': self.name, 'docstatus': 1}):
			self._has_sales_transaction = True
		else:
			self._has_sales_transaction = False

		return self._has_sales_transaction

	def has_billable_transaction(self):
		if getattr(self, '_has_billable_transaction', None):
			return self._has_billable_transaction

		has_billable_sales_order = frappe.db.get_value("Sales Order", {'project': self.name, 'docstatus': 1,
			'per_returned': ['<', 100]})
		has_billable_delivery_note = frappe.db.get_value("Delivery Note", {'project': self.name, 'docstatus': 1,
			'is_return': 0, 'per_returned': ['<', 100]})

		if has_billable_sales_order or has_billable_delivery_note:
			self._has_billable_transaction = True
		else:
			self._has_billable_transaction = False

		return self._has_billable_transaction

	def validate_project_type(self):
		if self.status in ('Completed', 'Closed', 'Cancelled'):
			return

		if self.project_type:
			project_type = frappe.get_cached_doc("Project Type", self.project_type)

			if project_type.bill_to_mandatory and not self.get('bill_to'):
				frappe.throw(_("Bill To is mandatory for Project Type {0}").format(self.project_type))

			if project_type.insurance_company_mandatory and not self.get('insurance_company'):
				frappe.throw(_("Insurance Company is mandatory for Project Type {0}").format(self.project_type))

			if project_type.campaign_mandatory and not self.get('campaign'):
				frappe.throw(_("Campaign is mandatory for Project Type {0}").format(self.project_type))

			if project_type.previous_project_mandatory and not self.get('previous_project'):
				frappe.throw(_("{0} is mandatory for Project Type {1}")
					.format(self.meta.get_label('previous_project'), self.project_type))

	def validate_cash_billing(self):
		bill_to = self.bill_to or self.customer
		cash_billing = frappe.get_cached_value("Customer", bill_to, "cash_billing")
		if cash_billing:
			self.cash_billing = 1

	def validate_appointment_required(self):
		if self.get('appointment'):
			return

		project_type = frappe.get_cached_doc("Project Type", self.project_type)
		appointment_required = project_type.is_internal != "Yes" and frappe.get_cached_value("Projects Settings", None, "appointment_required")
		appointment_bypassed = self.project_type and frappe.get_cached_value("Project Type", self.project_type, "appointment_not_required")

		if appointment_required and not appointment_bypassed:
			frappe.throw(_("Appointment is mandatory, please select an Appointment first"))

	def validate_appointment(self):
		if self.get('appointment'):
			appointment_details = frappe.db.get_value("Appointment", self.appointment,
				['name', 'status', 'docstatus'], as_dict=1)

			if not appointment_details:
				frappe.throw(_("Appointment {0} does not exist").format(self.appointment))

			if appointment_details.docstatus == 0:
				frappe.throw(_("{0} is not submitted").format(frappe.get_desk_link("Appointment", self.appointment)))
			if appointment_details.docstatus == 2:
				frappe.throw(_("{0} is cancelled").format(frappe.get_desk_link("Appointment", self.appointment)))
			if appointment_details.status == "Rescheduled":
				frappe.throw(_("{0} is {1}. Please select newer appointment instead")
					.format(frappe.get_desk_link("Appointment", self.appointment), frappe.bold(appointment_details.status)))

	def update_appointment(self):
		appointments = []
		if self.appointment:
			appointments.append(self.appointment)

		previous_appointment = self.get('_previous_appointment')
		if previous_appointment and previous_appointment not in appointments:
			appointments.append(previous_appointment)

		for appointment in appointments:
			doc = frappe.get_doc("Appointment", appointment)
			doc.set_status(update=True)
			doc.notify_update()

	def validate_phone_nos(self):
		if not self.get('contact_mobile') and self.get('contact_mobile_2'):
			self.contact_mobile = self.contact_mobile_2
			self.contact_mobile_2 = ''
		if self.get('contact_mobile') == self.get('contact_mobile_2'):
			self.contact_mobile_2 = ''

	def set_missing_values(self, for_validate=False):
		self.set_project_type_defaults()
		self.set_appointment_details()
		self.set_customer_details()
		self.set_applies_to_details(for_validate=for_validate)
		self.set_service_template_details()
		self.set_material_and_service_item_groups()

	def set_project_type_defaults(self):
		defaults = get_project_type_defaults(self.project_type)
		for k, v in defaults.items():
			if self.meta.has_field(k):
				self.set(k, v)

	def set_customer_details(self):
		args = self.as_dict()

		customer_details = get_customer_details(args)
		for k, v in customer_details.items():
			if self.meta.has_field(k) and not self.get(k) or k in self.force_customer_fields:
				self.set(k, v)

		bill_to_details = get_bill_to_details(args)
		for k, v in bill_to_details.items():
			if self.meta.has_field(k) and not self.get(k) or k in self.force_customer_fields:
				self.set(k, v)

	def get_billing_party(self):
		if self.get("bill_to"):
			return "Customer", self.bill_to, self.bill_to_name

		return self.get_party()

	def get_party(self):
		return "Customer", self.customer, self.customer_name

	@frappe.whitelist()
	def set_applies_to_details(self, for_validate=False):
		args = self.as_dict()
		applies_to_details = get_applies_to_details(args, for_validate=for_validate)

		for k, v in applies_to_details.items():
			if self.meta.has_field(k) and not self.get(k) or k in self.force_applies_to_fields:
				self.set(k, v)

	def get_checklist_rows(self, parentfield, rows=1):
		checklist = self.get(parentfield) or []
		per_row = ceil(len(checklist) / rows)

		out = []
		for i in range(rows):
			out.append([])

		for i, d in enumerate(checklist):
			row_id = i // per_row
			out[row_id].append(d)

		return out

	def set_service_template_details(self):
		for row in self.service_templates:
			self.set_service_template_details_for_row(row)
			if self.status not in ('Completed', 'Closed', 'Cancelled') and not row.has_sales_order:
				self.set_service_template_claim_customer_for_row(row)
				row.claim_customer_name = frappe.get_cached_value("Customer", row.claim_customer, "customer_name")

	def set_service_template_details_for_row(self, row):
		if row.service_template and not row.service_template_name:
			row.service_template_name = frappe.get_cached_value("Service Template", row.service_template,
				"service_template_name")

		if self.status not in ('Completed', 'Closed', 'Cancelled'):
			row.includes_service_warranty = frappe.get_cached_value("Service Template", row.service_template,
				"includes_service_warranty")

			if not row.has_sales_order:
				self.set_service_template_claim_customer_for_row(row)

	def set_service_template_claim_customer_for_row(self, row):
		row.claim_customer = None

	def set_appointment_details(self):
		if self.appointment:
			appointment_doc = frappe.get_doc("Appointment", self.appointment)

			self.appointment_dt = appointment_doc.scheduled_dt

			if not self.customer:
				customer = appointment_doc.get_customer()
				if customer:
					self.customer = customer
		else:
			self.appointment_dt = None

	def set_material_and_service_item_groups(self):
		settings = frappe.get_cached_doc("Projects Settings", None)
		self.materials_item_group = settings.materials_item_group
		self.lubricants_item_group = settings.lubricants_item_group
		self.sublet_item_group = settings.sublet_item_group
		self.consumables_item_group = settings.consumables_item_group
		self.paint_item_group = settings.paint_item_group

	def set_project_in_sales_order_and_quotation(self):
		if self.sales_order:
			frappe.db.set_value("Sales Order", self.sales_order, "project", self.name, notify=1)

			quotations = frappe.db.sql_list("""
				select distinct qtn.name
				from `tabQuotation` qtn
				inner join `tabSales Order Item` item on item.quotation = qtn.name
				where item.parent = %s and qtn.docstatus < 2 and ifnull(qtn.project, '') = ''
			""", self.sales_order)

			for quotation in quotations:
				frappe.db.set_value("Quotation", quotation, "project", self.name, notify=1)

	def validate_depreciation(self):
		if not self.insurance_company:
			self.default_depreciation_percentage = 0
			self.default_underinsurance_percentage = 0
			self.insurance_excess_amount = 0
			self.insurance_excess_percentage = 0
			self.non_standard_depreciation = []
			self.non_standard_underinsurance = []
			return

		if flt(self.default_depreciation_percentage) > 100:
			frappe.throw(_("Default Depreciation Rate cannot be greater than 100%"))

		if flt(self.default_underinsurance_percentage) > 100:
			frappe.throw(_("Default Underinsurance Rate cannot be greater than 100%"))

		if flt(self.insurance_excess_percentage) > 100:
			frappe.throw(_("Insurance Excess Percentage cannot be greater than 100%"))

		item_codes_visited = set()
		for d in self.non_standard_depreciation:
			if flt(d.depreciation_percentage) > 100:
				frappe.throw(_("Row #{0}: Depreciation Rate cannot be greater than 100%").format(d.idx))

			if d.depreciation_item_code in item_codes_visited:
				frappe.throw(_("Row #{0}: Duplicate Non Standard Depreciation row for Item {1}")
					.format(d.idx, frappe.bold(d.depreciation_item_code)))

		item_codes_visited = set()
		for d in self.non_standard_underinsurance:
			if flt(d.underinsurance_percentage) > 100:
				frappe.throw(_("Row #{0}: Underinsurance Rate cannot be greater than 100%").format(d.idx))

			if d.underinsurance_item_code in item_codes_visited:
				frappe.throw(_("Row #{0}: Duplicate Non Standard Underinsurance row for Item {1}")
					.format(d.idx, frappe.bold(d.underinsurance_item_code)))

			item_codes_visited.add(d.underinsurance_item_code)

	def validate_insurance_excess_billed_amount(self, for_proforma_invoice=False):
		total_excess = flt(self.insurance_excess_amount) + flt(self.additional_insurance_excess_amount)
		if not total_excess:
			return

		positive_excess, negative_excess = self.get_insurance_excess_billed(
			include_proforma_invoices=for_proforma_invoice
		)

		precision = self.precision("insurance_excess_amount")

		if (
			positive_excess - total_excess > 1 / 10 ** precision
			or negative_excess - total_excess > 1 / 10 ** precision
		):
			frappe.throw(_("Total Insurance Excess billed amount cannot be greater than {0}").format(
				frappe.format(total_excess, df=self.meta.get_field("insurance_excess_amount"))
			))

	def get_insurance_excess_billed(self, include_proforma_invoices=False):
		positive_excess = 0
		negative_excess = 0

		insurance_excess_item = frappe.get_cached_value("Projects Settings", None, "insurance_excess_item")
		if not insurance_excess_item:
			return positive_excess, negative_excess

		sinv_data = frappe.db.sql("""
			SELECT p.bill_to, i.base_amount, p.is_return
			FROM `tabSales Invoice Item` i
			INNER JOIN `tabSales Invoice` p ON i.parent = p.name
			WHERE p.docstatus = 1
				AND i.project = %s
				AND i.item_code = %s
		""", (self.name, insurance_excess_item), as_dict=1)

		pfinv_data = []
		if include_proforma_invoices:
			pfinv_data = frappe.db.sql("""
				SELECT p.bill_to, (i.amount - i.billed_amt) * p.conversion_rate as base_amount
				FROM `tabProforma Invoice Item` i
				INNER JOIN `tabProforma Invoice` p ON i.parent = p.name
				WHERE p.docstatus = 1
					AND p.project = %s
					AND i.item_code = %s
					AND i.billed_amt < i.amount
			""", (self.name, insurance_excess_item), as_dict=1)

		for d in sinv_data + pfinv_data:
			if d.base_amount < 0:
				if d.is_return:
					positive_excess += d.base_amount
				else:
					negative_excess -= d.base_amount
			else:
				if d.is_return:
					negative_excess -= d.base_amount
				else:
					positive_excess += d.base_amount

		return positive_excess, negative_excess

	def validate_warranty(self):
		if self.get('warranty_claim_denied'):
			self.warranty_claim_denied_reason = clean_whitespace(self.warranty_claim_denied_reason)
			if not self.warranty_claim_denied_reason:
				frappe.throw(_("Warranty Claim Denied Reason is mandatory for setting as Denied"))
		else:
			self.warranty_claim_denied_reason = None

	def validate_campaign(self):
		if self.status not in ('Completed', 'Closed', 'Cancelled'):
			validate_campaign_voucher_code(self)

	def set_items_and_totals_html_onload(self, sales_data, consumables_data):
		currency = erpnext.get_company_currency(self.company)

		service_items_html = frappe.render_template("erpnext/projects/doctype/project/project_items_table.html", {
			"title": _("Service Sales"),
			"doc": self,
			"data": sales_data.service_items,
			"currency": currency,
			"show_sales_order": True,
			"show_proforma_invoice": True,
			"show_amount": True,
		})

		material_items_html = frappe.render_template("erpnext/projects/doctype/project/project_items_table.html", {
			"title": _("Material Sales"),
			"doc": self,
			"data": sales_data.material_items,
			"currency": currency,
			"show_sales_order": True,
			"show_delivery_note": True,
			"show_proforma_invoice": True,
			"show_amount": True,
		})

		consumable_items_html = frappe.render_template("erpnext/projects/doctype/project/project_items_table.html", {
			"title": _("Consumables"),
			"doc": self,
			"data": consumables_data,
			"currency": currency,
			"show_material_request": True,
			"show_stock_entry": True,
		})

		sales_summary_html = frappe.render_template("erpnext/projects/doctype/project/project_sales_summary.html",
			{"doc": self, "currency": currency})

		self.set_onload('service_items_html', service_items_html)
		self.set_onload('material_items_html', material_items_html)
		self.set_onload('consumable_items_html', consumable_items_html)
		self.set_onload('sales_summary_html', sales_summary_html)

	def get_project_sales_data(self, get_sales_invoice=True):
		sales_data = frappe._dict()
		sales_data.material_items, sales_data.part_items, sales_data.lubricant_items, sales_data.consumable_items, sales_data.paint_items = get_material_items(self,
			get_sales_invoice=get_sales_invoice)
		sales_data.service_items, sales_data.labour_items, sales_data.hourly_labour_items, sales_data.package_items, sales_data.sublet_items, sales_data.sold_time = get_service_items(self,
			get_sales_invoice=get_sales_invoice)
		sales_data.totals = get_totals_data(self, [sales_data.material_items, sales_data.service_items])

		return sales_data

	def get_project_consumables_data(self):
		return get_consumable_items(self)

	def get_sales_invoices(self, exclude_indirect_invoice=False):
		if exclude_indirect_invoice:
			project_condition = "inv.project = %(project)s"
		else:
			project_condition = """inv.project = %(project)s or exists(
				select item.name from `tabSales Invoice Item` item
				where item.parent = inv.name and item.project = %(project)s)"""

		return frappe.db.sql("""
			select inv.name, inv.customer, inv.bill_to, inv.posting_date
			from `tabSales Invoice` inv
			where inv.docstatus = 1 and ({0})
			order by inv.posting_date, inv.posting_time, inv.creation
		""".format(project_condition), {'project': self.name}, as_dict=1)

	def get_sales_invoice_names(self):
		# Invoices
		invoices = self.get_sales_invoices()
		self.invoices = [d.name for d in invoices]

	def set_task_and_timelogs_html_onload(self, timelogs, tasks):
		from erpnext.projects.doctype.task.task import get_timelog_totals

		tasks_html = frappe.render_template("erpnext/projects/doctype/project/project_tasks_table.html", {
			"doc": self,
			"data": tasks,
		})

		timelogs_html = frappe.render_template("erpnext/projects/doctype/project/project_timelogs_table.html", {
			"doc": self,
			"data": timelogs,
			"totals": get_timelog_totals(timelogs),
		})

		self.set_onload('tasks_html', tasks_html)
		self.set_onload('timelogs_html', timelogs_html)

	def get_project_task_and_time_data(self):
		from erpnext.projects.doctype.task.task import (
			set_hrs_for_running_timelogs, get_task_status_color, add_tasks_actual_time_for_running_timelogs
		)

		timelogs = frappe.db.sql("""
			select tsd.parent as timesheet, tsd.name as timelog_row,
				ts.employee, ts.employee_name, 
				tsd.from_time, tsd.to_time,
				tsd.activity_type, tsd.hours,
				task.name as task, task.subject, task.task_type
			from `tabTimesheet Detail` tsd
			inner join `tabTimesheet` ts on ts.name = tsd.parent
			left join `tabTask` task on task.name = tsd.task
			where tsd.project = %s and tsd.docstatus < 2
			order by tsd.from_time
		""", self.name, as_dict=True)

		set_hrs_for_running_timelogs(timelogs)

		tasks = frappe.db.sql("""
			select task.name as task, task.subject, task.task_type, task.status,
				task.act_start_date, task.act_end_date,
				task.actual_time, task.expected_time,
				task.assigned_to, task.assigned_to_name, task.remarks
			from `tabTask` task
			where task.project = %s
			order by task.act_start_date is null, task.act_start_date, task.creation
		""", self.name, as_dict=True)

		for d in tasks:
			d.task_status_color = get_task_status_color(d.status)

		add_tasks_actual_time_for_running_timelogs(tasks, timelogs)

		return tasks, timelogs

	def set_project_date(self):
		self.project_date = getdate(
			self.expected_start_date
			or self.creation
		)

	def after_rename(self, old_name, new_name, merge=False):
		if old_name == self.copied_from:
			frappe.db.set_value('Project', new_name, 'copied_from', new_name)

	def get_item_groups_subtree(self, item_group):
		if (self.get('_item_group_subtree') or {}).get(item_group):
			return self._item_group_subtree[item_group]

		item_group_tree = []
		if item_group:
			item_group_tree = frappe.get_all("Item Group", {"name": ["subtree of", item_group]})
			item_group_tree = [d.name for d in item_group_tree]

		if not self.get('_item_group_subtree'):
			self._item_group_subtree = {}

		self._item_group_subtree[item_group] = item_group_tree

		return self._item_group_subtree[item_group]

	def validate_notification(self, notification_type=None, child_doctype=None, child_name=None, throw=False):
		if notification_type == "Ready to Close":
			# Notification should not be sent if status is not 'To Close'
			if self.status != "To Close":
				if throw:
					frappe.throw(_("Cannot send {0} notification because status is not 'To Close'").format(
						notification_type
					))
				return False

			# Notification should not be sent if not marked as ready to close
			if not self.ready_to_close:
				if throw:
					frappe.throw(_("Cannot send {0} notification because ready to close is not marked").format(
						notification_type
					))
				return False

		# Return True if no conditions catch any problem
		return True

	def set_pending_quotation_amount(self, update=False, update_modified=False):
		total = frappe.db.sql("""
			SELECT SUM(IF(base_rounded_total = 0, base_grand_total, base_rounded_total))
			FROM `tabQuotation`
			WHERE project = %s AND docstatus = 1 AND status = 'Open'
		""", self.name)
		total = flt(total[0][0]) if total else 0

		self.pending_quotation_amount = total

		if update:
			self.db_set({
				'pending_quotation_amount': self.pending_quotation_amount,
			}, update_modified=update_modified)

	def add_template_items_to_order(self, target_doc, bill_to=None, items_type=None):
		bill_to = bill_to or target_doc.get("bill_to") or self.bill_to or self.customer
		for row in self.service_templates:
			target_doc = self.add_template_items_to_order_for_row(target_doc, row, bill_to, items_type=items_type)

		return target_doc

	def add_template_items_to_order_for_row(self, target_doc, row, bill_to, items_type=None):
		from erpnext.projects.doctype.service_template.service_template import add_service_template_items

		project_customers = (self.to_bill, self.customer, self.insurance_company)
		project_customers = set(d for d in project_customers if d)
		claim_customers = set([d.claim_customer for d in self.service_templates
			if d.claim_customer and d.claim_customer not in project_customers])

		if (
			row.service_template
			and not row.get('sales_order')
			and (bill_to not in claim_customers or (row.claim_customer and bill_to == row.claim_customer))
		):
			target_doc = add_service_template_items(
				target_doc,
				row.service_template,
				applies_to_item=self.applies_to_item,
				applies_to_customer=bill_to,
				check_duplicate=False,
				service_template_detail=row,
				items_type=items_type,
				postprocess=False,
			)

		return target_doc


def get_material_items(project, get_sales_invoice=True):
	is_material_condition = "i.is_stock_item = 1"
	materials_item_groups = project.get_item_groups_subtree(project.materials_item_group)
	if materials_item_groups:
		is_material_condition = "(i.is_stock_item = 1 or i.item_group in ({0}))"\
			.format(", ".join([frappe.db.escape(d) for d in materials_item_groups]))

	pfinv_data = frappe.db.sql(f"""
		select
			p.name as proforma_invoice,
			p.bill_to,
			i.delivery_note,
			i.sales_order,
			if(so.transaction_date is null, p.transaction_date, so.transaction_date) as transaction_date,
			dn.posting_date, dn.posting_time,
			i.idx,
			i.item_code,
			i.item_name,
			i.description,
			i.item_group,
			i.is_stock_item,
			i.qty,
			i.uom,
			i.stock_uom,
			i.conversion_factor,
			i.base_net_amount as net_amount,
			i.base_net_rate as net_rate,
			i.base_taxable_amount as taxable_amount,
			i.base_tax_exclusive_total_discount as total_discount,
			i.item_tax_detail,
			p.conversion_rate
		from `tabProforma Invoice Item` i
		inner join `tabProforma Invoice` p on p.name = i.parent
		left join `tabDelivery Note` dn on dn.name = i.delivery_note
		left join `tabSales Order` so on so.name = i.sales_order
		where p.docstatus = 1
			and {is_material_condition}
			and p.project = %s
		order by transaction_date, p.creation, i.idx
	""" , project.name, as_dict=1)
	pre_process_items_data(pfinv_data, project)

	dn_data = frappe.db.sql(f"""
		select
			p.name as delivery_note,
			so.bill_to,
			i.sales_order,
			p.posting_date, p.posting_time,
			i.idx,
			i.item_code,
			i.item_name,
			i.description,
			i.item_group,
			i.is_stock_item,
			i.qty,
			i.proforma_qty as fulfilled_qty,
			i.uom,
			i.stock_uom,
			i.conversion_factor,
			i.base_net_amount as net_amount,
			i.base_net_rate as net_rate,
			i.base_taxable_amount as taxable_amount,
			i.base_tax_exclusive_total_discount as total_discount,
			i.item_tax_detail,
			p.conversion_rate,
			i.claim_customer
		from `tabDelivery Note Item` i
		inner join `tabDelivery Note` p on p.name = i.parent
		left join `tabSales Order` so on so.name = i.sales_order
		where p.docstatus = 1
			and {is_material_condition}
			and abs(i.proforma_qty) < abs(i.qty)
			and p.project = %s
	""", project.name, as_dict=1)
	pre_process_items_data(dn_data, project)

	so_data = frappe.db.sql(f"""
		select
			p.name as sales_order,
			p.bill_to,
			p.transaction_date,
			i.idx,
			i.item_code,
			i.item_name,
			i.description,
			i.item_group,
			i.is_stock_item,
			i.qty,
			greatest(if(i.is_stock_item = 1, i.delivered_qty, 0), i.proforma_qty) as fulfilled_qty,
			i.uom,
			i.stock_uom,
			i.conversion_factor,
			i.base_net_amount as net_amount,
			i.base_net_rate as net_rate,
			i.base_taxable_amount as taxable_amount,
			i.base_tax_exclusive_total_discount as total_discount,
			i.item_tax_detail,
			p.conversion_rate,
			i.claim_customer
		from `tabSales Order Item` i
		inner join `tabSales Order` p on p.name = i.parent
		where p.docstatus = 1
			and {is_material_condition}
			and (i.delivered_qty < i.qty or i.skip_delivery_note = 1)
			and i.proforma_qty < i.qty
			and i.qty > 0
			and (p.status != 'Closed' or exists(select sum(si_item.amount)
				from `tabSales Invoice Item` si_item
				where si_item.docstatus = 1 and si_item.sales_order_item = i.name and ifnull(si_item.delivery_note, '') = ''
				having sum(si_item.amount) > 0)
			)
			and p.project = %s
	""", project.name, as_dict=1)
	pre_process_items_data(so_data, project)

	sinv_data = frappe.db.sql(f"""
		select
			p.name as sales_invoice,
			p.bill_to,
			i.delivery_note,
			i.sales_order,
			i.proforma_invoice,
			p.posting_date, p.posting_time,
			i.idx,
			i.item_code,
			i.item_name,
			i.description,
			i.item_group,
			i.is_stock_item,
			i.qty,
			i.uom,
			i.stock_uom,
			i.conversion_factor,
			i.base_net_amount as net_amount,
			i.base_net_rate as net_rate,
			i.base_taxable_amount as taxable_amount,
			i.base_tax_exclusive_total_discount as total_discount,
			i.item_tax_detail,
			p.conversion_rate
		from `tabSales Invoice Item` i
		inner join `tabSales Invoice` p on p.name = i.parent
		where p.docstatus = 1
			and {is_material_condition}
			and ifnull(i.sales_order, '') = ''
			and ifnull(i.delivery_note, '') = ''
			and ifnull(i.proforma_invoice, '') = ''
			and i.project = %s
	""", project.name, as_dict=1)
	pre_process_items_data(sinv_data, project)

	materials_data = get_items_data_template()
	parts_data = get_items_data_template()
	lubricants_data = get_items_data_template()
	consumables_data = get_items_data_template()
	paint_material_data = get_items_data_template()

	lubricants_item_groups = project.get_item_groups_subtree(project.lubricants_item_group)
	consumables_item_group = project.get_item_groups_subtree(project.consumables_item_group)
	paint_material_item_group = project.get_item_groups_subtree(project.paint_item_group)
	for d in pfinv_data + dn_data + so_data + sinv_data:
		materials_data['items'].append(d)

		if d.item_group in lubricants_item_groups:
			lubricants_data['items'].append(d.copy())
		elif d.item_group in paint_material_item_group:
			paint_material_data['items'].append(d.copy())
		elif d.item_group in consumables_item_group:
			consumables_data['items'].append(d.copy())
		else:
			parts_data['items'].append(d.copy())

	materials_data['items'] = sorted(materials_data['items'], key=lambda d: (cstr(d.posting_date), cstr(d.posting_time), d.idx))
	parts_data['items'] = sorted(parts_data['items'], key=lambda d: (cstr(d.posting_date), cstr(d.posting_time), d.idx))
	lubricants_data['items'] = sorted(lubricants_data['items'], key=lambda d: (cstr(d.posting_date), cstr(d.posting_time), d.idx))
	consumables_data['items'] = sorted(consumables_data['items'], key=lambda d: (cstr(d.posting_date), cstr(d.posting_time), d.idx))
	paint_material_data['items'] = sorted(paint_material_data['items'],key=lambda d: (cstr(d.posting_date), cstr(d.posting_time), d.idx))

	get_item_taxes(project, materials_data, project.company)
	post_process_items_data(materials_data)

	get_item_taxes(project, parts_data, project.company)
	post_process_items_data(parts_data)

	get_item_taxes(project, lubricants_data, project.company)
	post_process_items_data(lubricants_data)

	get_item_taxes(project, consumables_data, project.company)
	post_process_items_data(consumables_data)

	get_item_taxes(project, paint_material_data, project.company)
	post_process_items_data(paint_material_data)

	return materials_data, parts_data, lubricants_data, consumables_data, paint_material_data


def get_service_items(project, get_sales_invoice=True):
	is_service_condition = "(i.is_stock_item = 0 and i.is_fixed_asset = 0)"
	materials_item_groups = project.get_item_groups_subtree(project.materials_item_group)
	if materials_item_groups:
		is_service_condition = "(i.is_stock_item = 0 and i.is_fixed_asset = 0 and (i.item_group not in ({0}) or i.item_group is null))"\
			.format(", ".join([frappe.db.escape(d) for d in materials_item_groups]))

	insurance_excess_item = frappe.get_cached_value("Projects Settings", None, "insurance_excess_item")
	exclude_insurance_excess = f" and i.item_code != {frappe.db.escape(insurance_excess_item)}" if insurance_excess_item else ""

	pfinv_data = frappe.db.sql(f"""
		select
			p.name as proforma_invoice,
			p.bill_to,
			i.delivery_note,
			i.sales_order,
			if(so.transaction_date is null, p.transaction_date, so.transaction_date) as transaction_date,
			i.idx,
			i.item_code,
			i.item_name,
			i.description,
			i.item_group,
			i.is_stock_item,
			i.qty,
			i.uom,
			i.stock_uom,
			i.conversion_factor,
			i.base_net_amount as net_amount,
			i.base_net_rate as net_rate,
			i.base_taxable_amount as taxable_amount,
			i.base_tax_exclusive_total_discount as total_discount,
			i.item_tax_detail,
			p.conversion_rate
		from `tabProforma Invoice Item` i
		inner join `tabProforma Invoice` p on p.name = i.parent
		left join `tabSales Order` so on so.name = i.sales_order
		where p.docstatus = 1
			and {is_service_condition}
			and p.project = %s
			{exclude_insurance_excess}
		order by transaction_date, p.creation, i.idx
	""", project.name, as_dict=1)
	pre_process_items_data(pfinv_data, project)

	so_data = frappe.db.sql(f"""
		select
			p.name as sales_order,
			p.bill_to,
			p.transaction_date,
			i.idx,
			i.item_code,
			i.item_name,
			i.description,
			i.item_group,
			i.is_stock_item,
			i.qty,
			i.proforma_qty as fulfilled_qty,
			i.uom,
			i.stock_uom,
			i.conversion_factor,
			i.base_net_amount as net_amount,
			i.base_net_rate as net_rate,
			i.base_taxable_amount as taxable_amount,
			i.base_tax_exclusive_total_discount as total_discount,
			i.item_tax_detail,
			p.conversion_rate,
			i.claim_customer
		from `tabSales Order Item` i
		inner join `tabSales Order` p on p.name = i.parent
		where p.docstatus = 1
			and {is_service_condition}
			and p.project = %s
			and i.proforma_qty < i.qty
			and (p.status != 'Closed' or exists(select sum(si_item.amount)
				from `tabSales Invoice Item` si_item
				where si_item.docstatus = 1 and si_item.sales_order_item = i.name
				having sum(si_item.amount) > 0)
			)
		order by p.transaction_date, p.creation, i.idx
	""", project.name, as_dict=1)
	pre_process_items_data(so_data, project)

	dn_data = frappe.db.sql(f"""
		select
			p.name as delivery_note,
			p.posting_date, p.posting_time,
			i.idx,
			i.item_code,
			i.item_name,
			i.description,
			i.item_group,
			i.is_stock_item,
			i.qty,
			i.proforma_qty as fulfilled_qty,
			i.uom,
			i.stock_uom,
			i.conversion_factor,
			i.base_net_amount as net_amount,
			i.base_net_rate as net_rate,
			i.base_taxable_amount as taxable_amount,
			i.base_tax_exclusive_total_discount as total_discount,
			i.item_tax_detail,
			p.conversion_rate,
			i.claim_customer
		from `tabDelivery Note Item` i
		inner join `tabDelivery Note` p on p.name = i.parent
		where p.docstatus = 1
			and {is_service_condition}
			and abs(i.proforma_qty) < abs(i.qty)
			and p.project = %s
			and ifnull(i.sales_order, '') = ''
	""", project.name, as_dict=1)
	pre_process_items_data(dn_data, project)

	sinv_data = []
	if get_sales_invoice:
		sinv_data = frappe.db.sql(f"""
			select
				p.name as sales_invoice,
				p.bill_to,
				i.delivery_note,
				i.sales_order,
				i.proforma_invoice,
				p.posting_date as transaction_date,
				i.idx,
				i.item_code,
				i.item_name,
				i.description,
				i.item_group,
				i.is_stock_item,
				i.qty,
				i.uom,
				i.stock_uom,
				i.conversion_factor,
				i.base_net_amount as net_amount,
				i.base_net_rate as net_rate,
				i.base_taxable_amount as taxable_amount,
				i.base_tax_exclusive_total_discount as total_discount,
				i.item_tax_detail,
				p.conversion_rate
			from `tabSales Invoice Item` i
			inner join `tabSales Invoice` p on p.name = i.parent
			where p.docstatus = 1
				and {is_service_condition}
				and ifnull(i.sales_order, '') = ''
				and ifnull(i.proforma_invoice, '') = ''
				and i.project = %s
				{exclude_insurance_excess}
			order by p.posting_date, p.creation, i.idx
		""", project.name, as_dict=1)
	pre_process_items_data(sinv_data, project)

	service_data = get_items_data_template()
	labour_data = get_items_data_template()
	hourly_labour_data = get_items_data_template()
	package_data = get_items_data_template()
	sublet_data = get_items_data_template()

	sublet_item_groups = project.get_item_groups_subtree(project.sublet_item_group)
	for d in pfinv_data + so_data + dn_data + sinv_data:
		service_data['items'].append(d)

		if d.item_group in sublet_item_groups:
			sublet_data['items'].append(d.copy())
		else:
			labour_data['items'].append(d.copy())
			# split the labour charges
			if d.uom == "Hour" or d.stock_uom == "Hour":
				hourly_labour_data['items'].append(d.copy())
			else:
				package_data['items'].append(d.copy())

	get_item_taxes(project, service_data, project.company)
	post_process_items_data(service_data)

	get_item_taxes(project, labour_data, project.company)
	post_process_items_data(labour_data)

	get_item_taxes(project, hourly_labour_data, project.company)
	post_process_items_data(hourly_labour_data)

	get_item_taxes(project, package_data, project.company)
	post_process_items_data(package_data)

	get_item_taxes(project, sublet_data, project.company)
	post_process_items_data(sublet_data)

	sold_time = get_sold_time(labour_data['items'])

	return service_data, labour_data, hourly_labour_data, package_data, sublet_data, sold_time


def get_sold_time(items):
	sold_time = 0
	for d in items:
		hours = convert_item_uom_for(
			d.qty, d.item_code, d.uom, "Hour",
			conversion_factor=d.conversion_factor if d.stock_uom == "Hour" else None,
			null_if_not_convertible=True
		)

		if hours is not None:
			sold_time += hours

	return sold_time


def get_consumable_items(project):
	ste_data = frappe.db.sql("""
		select p.name as stock_entry, p.purpose, i.material_request,
			p.posting_date, p.posting_time, i.idx,
			i.item_code, i.item_name, i.description, i.item_group,
			i.qty, i.uom
		from `tabStock Entry Detail` i
		inner join `tabStock Entry` p on p.name = i.parent
		where p.docstatus = 1 and p.project = %s and p.purpose in ('Material Issue', 'Material Receipt')
		order by p.posting_date, p.creation, i.idx
	""", project.name, as_dict=1)

	mreq_data = frappe.db.sql("""
		select p.name as material_request,
			p.transaction_date, i.idx,
			i.item_code, i.item_name, i.description, i.item_group,
			(i.stock_qty - i.received_qty) / i.conversion_factor as qty,
			i.qty as requested_qty,
			i.received_qty,
			i.uom
		from `tabMaterial Request Item` i
		inner join `tabMaterial Request` p on p.name = i.parent
		where p.docstatus = 1
			and p.material_request_type = 'Material Issue'
			and i.received_qty < i.stock_qty
			and p.status != 'Stopped'
			and p.project = %s
		order by p.transaction_date, p.creation, i.idx
	""", project.name, as_dict=1)

	consumables_data = frappe._dict({'total_qty': 0, 'items': []})

	for d in ste_data:
		if d.purpose == "Material Receipt":
			d.qty *= -1

	for d in ste_data + mreq_data:
		consumables_data['items'].append(d)

	consumables_data['items'] = sorted(consumables_data['items'], key=lambda d: (cstr(d.posting_date), cstr(d.posting_time), d.idx))
	for i, d in enumerate(consumables_data['items']):
		d.idx = i + 1
		consumables_data.total_qty += d.qty

	return consumables_data


def get_items_data_template():
	return frappe._dict({
		'total_qty': 0,

		'net_total': 0,
		'customer_net_total': 0,
		'insurance_net_total': 0,

		'total_discount': 0,

		'taxable_total': 0,

		'sales_taxable_total': 0,
		'sales_tax_total': 0,
		'customer_sales_tax_total': 0,

		'service_taxable_total': 0,
		'service_tax_total': 0,
		'customer_service_tax_total': 0,

		'other_taxes_and_charges': 0,
		'customer_other_taxes_and_charges': 0,

		'taxes': {},
		'customer_taxes': {},

		'items': [],
	})


def pre_process_items_data(data, project):
	adjust_sales_data_fulfilled_qty(data)
	set_depreciation_in_invoice_items(data, project, force=True)
	set_sales_data_customer_amounts(data, project)


def adjust_sales_data_fulfilled_qty(data):
	for d in data:
		if not flt(d.fulfilled_qty):
			continue

		d.original_qty = flt(d.qty)
		d.qty = max(flt(flt(d.qty) - flt(d.fulfilled_qty), 9), 0)
		ratio = d.qty / d.original_qty if d.original_qty else 0

		d.net_amount *= ratio
		d.taxable_amount *= ratio
		d.total_discount *= ratio


def set_sales_data_customer_amounts(data, project):
	project_customers = (project.customer, project.bill_to)
	project_customers = set(c for c in project_customers if c)

	for d in data:
		d.bill_to = d.bill_to or project.bill_to or project.customer
		is_goodwill_customer = frappe.get_cached_value("Customer", d.bill_to, "is_goodwill_customer")
		d.has_customer_depreciation = 0
		d.is_claim_item = 0
		d.is_other_customer_item = 0

		if d.get('claim_customer') and project.customer and d.get('claim_customer') != project.customer:
			d.is_claim_item = 1

			if d.total_discount:
				d.customer_net_amount = d.net_amount
				d.customer_net_rate = d.net_rate
				d.net_amount = d.customer_net_amount + d.total_discount
				d.net_rate = d.net_amount / d.qty if d.qty else d.net_amount
			else:
				d.customer_net_amount = 0
				d.customer_net_rate = 0

		elif (
			project.insurance_company
			and project.customer != project.insurance_company
			and d.bill_to == project.insurance_company
		):
			d.has_customer_depreciation = 1

			depreciation_amount = d.net_amount * flt(d.depreciation_percentage) / 100
			underinsurance_amount = (d.net_amount - depreciation_amount) * flt(d.underinsurance_percentage) / 100
			d.customer_net_amount = depreciation_amount + underinsurance_amount

			depreciation_rate = d.net_rate * flt(d.depreciation_percentage) / 100
			underinsurance_rate = (d.net_rate - depreciation_rate) * flt(d.underinsurance_percentage) / 100
			d.customer_net_rate = depreciation_rate + underinsurance_rate

			d.cumulative_depreciation_percentage = d.customer_net_amount / d.net_amount * 100 if d.net_amount else 0

		elif (
			d.bill_to in project_customers
			and (not is_goodwill_customer or d.bill_to == project.customer)
		):
			d.customer_net_amount = d.net_amount
			d.customer_net_rate = d.net_rate

		else:
			d.is_other_customer_item = 1
			d.customer_net_amount = 0
			d.customer_net_rate = 0


def get_item_taxes(project, data, company):
	sales_tax_account = frappe.get_cached_value('Company', company, "sales_tax_account")
	service_tax_account = frappe.get_cached_value('Company', company, "service_tax_account")

	for d in data['items']:
		conversion_rate = flt(d.get('conversion_rate')) or 1

		d.setdefault('taxes', {})
		d.setdefault('customer_taxes', {})

		d.setdefault('sales_tax_amount', 0)
		d.setdefault('customer_sales_tax_amount', 0)

		d.setdefault('service_tax_amount', 0)
		d.setdefault('customer_service_tax_amount', 0)

		d.setdefault('other_taxes_and_charges', 0)
		d.setdefault('customer_other_taxes_and_charges', 0)

		if project.get('has_stin'):
			item_tax_detail = json.loads(d.item_tax_detail or '{}')
			for tax_row_name, amount in item_tax_detail.items():
				tax_account = frappe.db.get_value("Sales Taxes and Charges", tax_row_name, 'account_head', cache=1)
				if tax_account:
					tax_amount = flt(amount)
					tax_amount *= conversion_rate

					customer_tax_amount = flt(amount)
					if d.get('is_other_customer_item') or (d.get('is_claim_item') and not d.get('total_discount')):
						customer_tax_amount = 0
					if d.has_customer_depreciation:
						customer_tax_amount *= d.cumulative_depreciation_percentage / 100

					customer_tax_amount *= conversion_rate

					if flt(d.original_qty):
						tax_amount = tax_amount * flt(d.qty) / flt(d.original_qty)
						customer_tax_amount = customer_tax_amount * flt(d.qty) / flt(d.original_qty)

					d.taxes.setdefault(tax_account, 0)
					d.taxes[tax_account] += tax_amount

					d.customer_taxes.setdefault(tax_account, 0)
					d.customer_taxes[tax_account] += customer_tax_amount

					if tax_account == sales_tax_account:
						d.sales_tax_amount += tax_amount
						d.customer_sales_tax_amount += customer_tax_amount
					elif tax_account == service_tax_account:
						d.service_tax_amount += tax_amount
						d.customer_service_tax_amount += customer_tax_amount
					else:
						d.other_taxes_and_charges += tax_amount
						d.customer_other_taxes_and_charges += customer_tax_amount


def post_process_items_data(data):
	for i, d in enumerate(data['items']):
		d.idx = i + 1

		data.total_qty += flt(d.qty)

		data.net_total += flt(d.net_amount)
		data.customer_net_total += flt(d.customer_net_amount)
		if d.has_customer_depreciation:
			data.insurance_net_total += flt(d.net_amount)

		data.total_discount += flt(d.total_discount)

		data.taxable_total += flt(d.taxable_amount)
		if flt(d.sales_tax_amount):
			data.sales_taxable_total += flt(d.taxable_amount)
		if flt(d.service_tax_amount):
			data.service_taxable_total += flt(d.taxable_amount)

		data.sales_tax_total += flt(d.sales_tax_amount)
		data.customer_sales_tax_total += flt(d.customer_sales_tax_amount)

		data.service_tax_total += flt(d.service_tax_amount)
		data.customer_service_tax_total += flt(d.customer_service_tax_amount)

		data.other_taxes_and_charges += flt(d.other_taxes_and_charges)
		data.customer_other_taxes_and_charges += flt(d.customer_other_taxes_and_charges)

		for tax_account, tax_amount in d.taxes.items():
			data.taxes.setdefault(tax_account, 0)
			data.taxes[tax_account] += tax_amount
		for tax_account, tax_amount in d.customer_taxes.items():
			data.customer_taxes.setdefault(tax_account, 0)
			data.customer_taxes[tax_account] += tax_amount

	data.sales_tax_rate = data.sales_tax_total / data.sales_taxable_total * 100 if data.sales_taxable_total else 0
	data.service_tax_rate = data.service_tax_total / data.service_taxable_total * 100 if data.service_taxable_total else 0


def get_totals_data(project, items_dataset):
	totals_data = frappe._dict({
		'taxes': {},
		'customer_taxes': {},

		'sales_tax_total': 0,
		'customer_sales_tax_total': 0,

		'service_tax_total': 0,
		'customer_service_tax_total': 0,

		'other_taxes_and_charges': 0,
		'customer_other_taxes_and_charges': 0,

		'total_taxes_and_charges': 0,
		'customer_total_taxes_and_charges': 0,

		'net_total': 0,
		'customer_net_total': 0,
		'insurance_net_total': 0,

		'total_discount': 0,

		'taxable_total': 0,
		'sales_taxable_total': 0,
		'service_taxable_total': 0,

		'sales_tax_rate': 0,
		'service_tax_rate': 0,

		'grand_total': 0,
		'customer_grand_total': 0,
	})
	for data in items_dataset:
		totals_data.net_total += flt(data.net_total)
		totals_data.customer_net_total += flt(data.customer_net_total)
		totals_data.insurance_net_total += flt(data.insurance_net_total)

		totals_data.total_discount += flt(data.total_discount)

		totals_data.taxable_total += flt(data.taxable_total)
		totals_data.sales_taxable_total += flt(data.sales_taxable_total)
		totals_data.service_taxable_total += flt(data.service_taxable_total)

		totals_data.sales_tax_total += flt(data.sales_tax_total)
		totals_data.customer_sales_tax_total += flt(data.customer_sales_tax_total)

		totals_data.service_tax_total += flt(data.service_tax_total)
		totals_data.customer_service_tax_total += flt(data.customer_service_tax_total)

		totals_data.other_taxes_and_charges += flt(data.other_taxes_and_charges)
		totals_data.customer_other_taxes_and_charges += flt(data.customer_other_taxes_and_charges)

		for tax_account, tax_amount in data.taxes.items():
			totals_data.taxes.setdefault(tax_account, 0)
			totals_data.taxes[tax_account] += tax_amount
			totals_data.total_taxes_and_charges += tax_amount

		for tax_account, tax_amount in data.customer_taxes.items():
			totals_data.customer_taxes.setdefault(tax_account, 0)
			totals_data.customer_taxes[tax_account] += tax_amount
			totals_data.customer_total_taxes_and_charges += tax_amount

	# Tax Rate
	totals_data.sales_tax_rate = totals_data.sales_tax_total / totals_data.sales_taxable_total * 100\
		if totals_data.sales_taxable_total else 0
	totals_data.service_tax_rate = totals_data.service_tax_total / totals_data.service_taxable_total * 100\
		if totals_data.service_taxable_total else 0

	# Insurance Excess
	if (
		project.insurance_company
		and project.insurance_company != project.customer
		and (flt(project.insurance_excess_amount) or flt(project.insurance_excess_percentage))
	):
		insurance_excess_total = 0
		if flt(project.insurance_excess_percentage):
			insurance_excess_total += totals_data.insurance_net_total * flt(project.insurance_excess_percentage) / 100
		if flt(project.insurance_excess_amount):
			insurance_excess_total += flt(project.insurance_excess_amount)

		totals_data.customer_net_total += insurance_excess_total

		sales_tax_account = frappe.get_cached_value('Company', project.company, "sales_tax_account")
		if sales_tax_account and totals_data.sales_tax_rate:
			tax_amount = insurance_excess_total * totals_data.sales_tax_rate / 100
			totals_data.customer_taxes.setdefault(sales_tax_account, 0)
			totals_data.customer_taxes[sales_tax_account] += tax_amount
			totals_data.customer_sales_tax_total += tax_amount
			totals_data.customer_total_taxes_and_charges += tax_amount

	# Grand Total
	totals_data.grand_total += totals_data.net_total + totals_data.total_taxes_and_charges
	totals_data.customer_grand_total += totals_data.customer_net_total + totals_data.customer_total_taxes_and_charges

	grand_total_precision = get_field_precision(frappe.get_meta("Sales Invoice").get_field("grand_total"),
		currency=frappe.get_cached_value('Company', project.company, "default_currency"))
	totals_data.grand_total = flt(totals_data.grand_total, grand_total_precision)
	totals_data.customer_grand_total = flt(totals_data.customer_grand_total, grand_total_precision)

	return totals_data


def get_timeline_data(doctype, name):
	'''Return timeline for attendance'''
	return dict(frappe.db.sql('''select unix_timestamp(from_time), count(*)
		from `tabTimesheet Detail` where project=%s
			and from_time > date_sub(curdate(), interval 1 year)
			and docstatus < 2
			group by date(from_time)''', name))


@frappe.whitelist()
def create_kanban_board_if_not_exists(project):
	from frappe.desk.doctype.kanban_board.kanban_board import quick_kanban_board

	if not frappe.db.exists('Kanban Board', project):
		quick_kanban_board('Task', project, 'status')

	return True


@frappe.whitelist()
def set_project_ready_to_close(project):
	project = frappe.get_doc('Project', project)
	project.check_permission('write')

	project.set_ready_to_close(update=True)
	project.set_timesheet_values(update=True)
	project.set_status(update=True, status="To Close", reset=True, from_doctype="Project", action="ready_to_close")
	project.run_method('notify_ready_to_close')
	project.notify_update()


@frappe.whitelist()
def reopen_project_status(project):
	project = frappe.get_doc('Project', project)
	project.check_permission('write')

	project.reopen_status(update=True)
	project.set_timesheet_values(update=True)
	project.set_status(update=True, status="Open", reset=True, from_doctype="Project", action="reopen")
	project.notify_update()


@frappe.whitelist()
def set_project_status(project, project_status):
	project = frappe.get_doc('Project', project)
	project.check_permission('write')

	project.set_status(status=project_status, update=True, from_doctype="Project", action="set_status")
	project.save()


@frappe.whitelist()
def get_customer_details(args):
	if isinstance(args, str):
		args = json.loads(args)

	args = frappe._dict(args)
	out = frappe._dict()

	customer = frappe._dict()
	if args.customer:
		customer = frappe.get_cached_doc("Customer", args.customer)

	out.customer_name = customer.customer_name
	out.customer_group = customer.customer_group

	# Tax IDs
	out.tax_id = customer.tax_id
	out.tax_cnic = customer.tax_cnic
	out.tax_strn = customer.tax_strn
	out.tax_status = customer.tax_status

	# Customer Address
	out.customer_address = args.customer_address
	if not out.customer_address and customer.name:
		out.customer_address = get_default_address("Customer", customer.name)

	out.address_display = get_address_display(out.customer_address)

	# Contact
	out.contact_person = args.contact_person
	if not out.contact_person and customer.name:
		out.contact_person = get_default_contact("Customer", customer.name)

	out.update(get_contact_details(out.contact_person))

	out.secondary_contact_person = args.secondary_contact_person
	secondary_contact_details = get_contact_details(out.secondary_contact_person, prefix="secondary_")
	out.update(secondary_contact_details)

	out.contact_nos = get_all_contact_nos("Customer", customer.name)

	return out


@frappe.whitelist()
def get_bill_to_details(args):
	if isinstance(args, str):
		args = json.loads(args)

	args = frappe._dict(args)
	out = frappe._dict()

	bill_to = frappe._dict()
	if args.bill_to:
		bill_to = frappe.get_cached_doc("Customer", args.bill_to)

	out.bill_to_name = bill_to.customer_name
	out.bill_to_customer_group = bill_to.customer_group

	# Contact
	out.billing_contact_person = args.billing_contact_person
	if not out.billing_contact_person and bill_to.name:
		out.billing_contact_person = get_default_contact("Customer", bill_to.name)

	out.update(get_contact_details(out.billing_contact_person, prefix="billing_"))

	# Billing Address
	out.billing_address = args.billing_address
	if not out.billing_address and bill_to.name:
		out.billing_address = get_default_address("Customer", bill_to.name)

	out.billing_address_display = get_address_display(out.billing_address)

	return out


@frappe.whitelist()
def get_project_details(project, doctype, purpose=None):
	from erpnext.controllers.transaction_controller import is_doctype_selling_or_buying

	if isinstance(project, str):
		project = frappe.get_doc("Project", project)

	is_sales_doctype = is_doctype_selling_or_buying(doctype) == "selling"

	out = frappe._dict()
	out['project_reference_no'] = project.get('reference_no')

	fieldnames = [
		'company', 'branch',
		'customer', 'bill_to',
		'applies_to_item', 'applies_to_serial_no',
		'service_advisor',
		'insurance_company', 'insurance_loss_no', 'insurance_policy_no',
		'insurance_surveyor', 'insurance_surveyor_company',
		'has_stin', 'default_depreciation_percentage', 'default_underinsurance_percentage',
		'campaign', 'campaign_voucher_code', 'cost_center', 'project_date',
	]
	sales_only_fields = [
		'customer', 'bill_to', 'has_stin',
		'default_depreciation_percentage', 'default_underinsurance_percentage',
	]
	ignore_empty_fields = ['customer', 'bill_to']

	# Copy fields
	force_fields = []
	if doctype == "Material Request":
		force_fields.append("customer")

	for f in fieldnames:
		if f in sales_only_fields and not is_sales_doctype and f not in force_fields:
			continue
		if f in ignore_empty_fields and not project.get(f):
			continue

		out[f] = project.get(f)

		if f == "customer":
			if doctype == "Quotation":
				out['quotation_to'] = 'Customer'
				out['party_name'] = project.get(f)
			elif doctype == "Customer Feedback":
				out['feedback_from'] = 'Customer'
				out['party_name'] = project.get(f)

	# Contact and Address
	if is_sales_doctype:
		if project.get("bill_to") and frappe.get_meta(doctype).has_field("bill_to"):
			out.contact_person = project.billing_contact_person
			out.customer_address = project.billing_address
		else:
			out.contact_person = project.contact_person
			out.contact_mobile = project.contact_mobile
			out.contact_phone = project.contact_phone
			out.customer_address = project.customer_address

	# Warehouse
	default_warehouse = project.default_warehouse
	if doctype in ("Material Request", "Stock Entry"):
		default_warehouse = project.consumables_warehouse or project.default_warehouse

	if default_warehouse:
		out.set_warehouse = default_warehouse

		if purpose == "Material Issue":
			out.from_warehouse = default_warehouse
		elif purpose == "Material Receipt":
			out.to_warehouse = default_warehouse

	frappe.utils.call_hook_method("get_project_details", project, out, doctype)

	return out


def get_service_template_quoted_set(project):
	service_template_quoted_set = []

	service_template_details = [d.name for d in project.service_templates if d.name]
	if service_template_details:
		service_template_quoted_set = frappe.db.sql_list("""
			select distinct item.service_template_detail
			from `tabQuotation Item` item
			inner join `tabQuotation` qtn on qtn.name = item.parent
			where qtn.docstatus = 1 and qtn.project = %s and item.service_template_detail in %s
		""", (project.name, service_template_details))

	return service_template_quoted_set


def get_service_template_ordered_set(project, group_by_item_type=False):
	service_template_ordered_set = []

	service_template_details = [d.name for d in project.service_templates if d.name]
	if service_template_details:
		service_template_ordered_set = frappe.db.sql("""
			select distinct item.service_template_detail, item.is_stock_item
			from `tabSales Order Item` item
			inner join `tabSales Order` so on so.name = item.parent
			where so.docstatus = 1 and so.project = %s and item.service_template_detail in %s
		""", (project.name, service_template_details), pluck="service_template_detail" if not group_by_item_type else None)

	return service_template_ordered_set


def get_service_template_requested_set(project):
	service_template_requested_set = []

	service_template_details = [d.name for d in project.service_templates if d.name]
	if service_template_details:
		service_template_requested_set = frappe.db.sql_list("""
			select distinct item.service_template_detail
			from `tabMaterial Request Item` item
			inner join `tabMaterial Request` mreq on mreq.name = item.parent
			where mreq.docstatus = 1 and mreq.project = %s and item.service_template_detail in %s
		""", (project.name, service_template_details))

	return service_template_requested_set


def get_service_template_warranty_set(project):
	service_template_warranty_set = []

	service_template_details = [d.name for d in project.service_templates if d.name]
	if service_template_details:
		service_template_warranty_set = frappe.db.sql_list("""
			select distinct wty.service_template_detail
			from `tabService Warranty` wty
			where wty.docstatus = 1 and wty.project = %s and wty.service_template_detail in %s
		""", (project.name, service_template_details))

	return service_template_warranty_set


def set_depreciation_in_invoice_items(items_list, project, force=False):
	non_standard_depreciation_items = {}
	for d in project.non_standard_depreciation:
		if d.depreciation_item_code:
			non_standard_depreciation_items[d.depreciation_item_code] = flt(d.depreciation_percentage)

	non_standard_underinsurance_items = {}
	for d in project.non_standard_underinsurance:
		if d.underinsurance_item_code:
			non_standard_underinsurance_items[d.underinsurance_item_code] = flt(d.underinsurance_percentage)

	materials_item_groups = project.get_item_groups_subtree(project.materials_item_group)

	for d in items_list:
		is_material = d.is_stock_item or d.item_group in materials_item_groups
		if is_material or d.item_code in non_standard_depreciation_items:
			if force or not flt(d.depreciation_percentage):
				if d.item_code in non_standard_depreciation_items:
					d.depreciation_percentage = non_standard_depreciation_items[d.item_code]
				else:
					d.depreciation_percentage = flt(project.default_depreciation_percentage)
		else:
			d.depreciation_percentage = 0

		if force or not flt(d.underinsurance_percentage):
			if d.item_code in non_standard_underinsurance_items:
				d.underinsurance_percentage = non_standard_underinsurance_items[d.item_code]
			else:
				d.underinsurance_percentage = flt(project.default_underinsurance_percentage)


@frappe.whitelist()
def set_warranty_claim_denied(projects, denied, reason=None):
	if isinstance(projects, str):
		projects = json.loads(projects)

	denied = cint(denied)

	for name in projects:
		doc = frappe.get_doc("Project", name)
		doc.warranty_claim_denied = denied
		doc.warranty_claim_denied_reason = reason
		doc.save()
