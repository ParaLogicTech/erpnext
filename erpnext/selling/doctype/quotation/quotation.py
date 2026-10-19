# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.model.mapper import get_mapped_doc
from frappe.utils import flt, nowdate, getdate, cint, add_days, date_diff, now_datetime, combine_datetime, get_time
from frappe import _
from erpnext.overrides.lead.lead_hooks import get_customer_from_lead
from erpnext.controllers.selling_controller import SellingController
from frappe.core.doctype.notification_count.notification_count import (
	get_all_notification_count,
	get_notification_last_scheduled,
	set_notification_last_scheduled,
)
from frappe.email.doctype.notification.notification import has_notification

form_grid_templates = {
	"items": "templates/form_grid/item_grid.html"
}


class Quotation(SellingController):
	def validate(self):
		super(Quotation, self).validate()
		self.validate_quotation_valid_till()
		self.validate_delivery_date()
		self.validate_project()
		self.validate_previous_orders()
		self.validate_campaign()
		self.validate_warehouse()
		self.validate_items_carton_type()
		self.clear_approval_date()
		self.set_customer_name()
		self.sort_items()

		if self.items:
			self.with_items = 1

		self.set_ordered_status()
		self.set_status()
		self.set_title()

	def before_submit(self):
		self.validate_item_code_mandatory()
		self.submission_date = getdate()

	def on_submit(self):
		# Check for Approving Authority
		frappe.get_doc('Authorization Control').validate_approving_authority(self.doctype,
			self.company, self.base_grand_total, self)

		# update enquiry status
		self.update_opportunity()
		self.update_lead_status()
		self.update_project_quotation_status()

	def on_cancel(self):
		if self.lost_reasons:
			self.lost_reasons = []

		# update enquiry status
		self.update_status_on_cancel()
		self.update_opportunity()
		self.update_lead_status(status="Interested")
		self.update_project_quotation_status()

	def clear_approval_date(self):
		self.approval_date = None

	def before_update_after_submit(self):
		super().before_update_after_submit()
		self.validate_approval_date()

	def onload(self):
		super(Quotation, self).onload()
		if self.quotation_to == "Customer":
			self.set_onload('customer', self.party_name)
		elif self.quotation_to == "Lead":
			self.set_onload('customer', get_customer_from_lead(self.party_name))

		self.set_onload('notification_count', get_all_notification_count(self.doctype, self.name))
		self.set_can_notify_onload()
		self.set_scheduled_reminder_onload()

	def set_missing_values(self, for_validate=False):
		super().set_missing_values(for_validate)
		self.set_missing_delivery_date()
		self.set_previous_order_values()

	def validate_delivery_date(self):
		if cint(self.lead_time_days) < 0:
			frappe.throw(_("{0} cannot be negative").format(self.meta.get_label("lead_time_days")))

		if self.delivery_date and getdate(self.delivery_date) < getdate(self.transaction_date):
			frappe.throw(_("Expected Delivery Date must be after Quotation Date"))

	def validate_approval_date(self):
		if self.approval_date and getdate(self.approval_date) < getdate(self.transaction_date):
			frappe.throw(_("Approval Date must be after Quotation Date"))
		if self.approval_date and getdate(self.approval_date) > getdate():
			frappe.throw(_("Approval Date cannot be in the future"))

	def set_missing_delivery_date(self):
		if cint(self.lead_time_days) > 0:
			self.delivery_date = add_days(getdate(self.transaction_date), cint(self.lead_time_days))

		if not cint(self.lead_time_days) and self.delivery_date:
			self.lead_time_days = date_diff(self.delivery_date, self.transaction_date)
			if self.lead_time_days < 0:
				self.lead_time_days = 0

	def set_previous_order_values(self):
		for d in self.get("previous_orders"):
			d.update(get_previous_order_details(d.previous_sales_order))

	def validate_previous_orders(self):
		visited = set()
		for d in self.get("previous_orders"):
			if d.previous_sales_order in visited:
				frappe.throw(_("Row #{0}: Previous Sales Order {1} is entered twice").format(
					d.idx, frappe.bold(d.previous_sales_order)
				))
			else:
				visited.add(d.previous_sales_order)

			so_details = frappe.db.get_value("Sales Order", d.previous_sales_order, fieldname=[
				"docstatus", "status", "currency", "project",
			], as_dict=True)

			if not so_details:
				frappe.throw(_("Sales Order {0} does not exist").format(d.previous_sales_order))

			if so_details.docstatus != 1:
				frappe.throw(_("Row #{0}: Previous Sales Order {1} is not submitted").format(
					d.idx, frappe.bold(d.previous_sales_order)
				))
			if so_details.status == "Closed":
				frappe.throw(_("Row #{0}: Previous Sales Order {1} is Closed").format(
					d.idx, frappe.bold(d.previous_sales_order)
				))
			if self.currency and so_details.currency != self.currency:
				frappe.throw(_("Row #{0}: Previous Sales Order {1} currency {2} does not match with this Quotation").format(
					d.idx, frappe.bold(d.previous_sales_order), so_details.currency,
				))
			if self.project and so_details.project != self.project:
				frappe.throw(_("Row #{0}: Previous Sales Order {1} does not belong to {2} {3}").format(
					d.idx,
					frappe.bold(d.previous_sales_order),
					_("Project"),
					frappe.bold(self.project),
				))

	def set_ordered_status(self, update=False, update_modified=True):
		ordered_qty_map = self.get_ordered_qty_map()
		for d in self.items:
			d.ordered_qty = flt(ordered_qty_map.get(d.name))
			if update:
				d.db_set({
					'ordered_qty': d.ordered_qty,
				}, update_modified=update_modified)

	def get_ordered_qty_map(self):
		ordered_qty_map = {}

		if self.docstatus == 1:
			row_names = [d.name for d in self.items]

			if row_names:
				ordered_qty_map = dict(frappe.db.sql("""
					select i.quotation_item, sum(i.qty)
					from `tabSales Order Item` i
					inner join `tabSales Order` p on p.name = i.parent
					where p.docstatus = 1 and i.quotation_item in %s
					group by i.quotation_item
				""", [row_names]))

			unordered_rows = list(set(row_names) - set(ordered_qty_map.keys()))
			if unordered_rows:
				billed_qty_map = dict(frappe.db.sql("""
					select i.quotation_item, sum(i.qty)
					from `tabSales Invoice Item` i
					inner join `tabSales Invoice` p on p.name = i.parent
					where p.docstatus = 1 and i.quotation_item in %s
					group by i.quotation_item
				""", [row_names]))

				for quotation_item, billed_qty in billed_qty_map.items():
					if quotation_item not in ordered_qty_map:
						ordered_qty_map[quotation_item] = billed_qty

		return ordered_qty_map

	def set_status(self, update=False, status=None, update_modified=True):
		previous_status = self.status
		today = getdate()

		# Draft
		if self.docstatus == 0:
			self.status = "Draft"

		# Cancelled
		elif self.docstatus == 2:
			self.status = "Cancelled"

		# Submitted
		else:
			if status:
				self.status = status

			if self.has_sales_order_or_invoice():
				self.status = "Ordered"
			elif self.status in ("Lost", "Approved"):
				pass
			elif self.valid_till and getdate(self.valid_till) < today:
				self.status = "Expired"
			else:
				self.status = "Open"

		# Missing Approval Date
		if self.status in ("Ordered", "Approved") and not self.approval_date:
			self.approval_date = today

		self.add_status_comment(previous_status)

		if update:
			self.db_set({
				"status": self.status,
				"approval_date": self.approval_date,
			}, update_modified=update_modified)

	def update_lead_status(self, status=None):
		if self.quotation_to == "Lead" and self.party_name:
			doc = frappe.get_doc("Lead", self.party_name)
			doc.set_status(update=True, status=status)
			doc.notify_update()

	def update_opportunity(self):
		if self.get('opportunity'):
			opp = frappe.get_doc("Opportunity", self.opportunity)
			opp.set_status(update=True)
			opp.notify_update()

	def has_sales_order_or_invoice(self):
		return frappe.db.get_value("Sales Order Item", {"quotation": self.name, "docstatus": 1})\
			or frappe.db.get_value("Sales Invoice Item", {"quotation": self.name, "docstatus": 1})

	@frappe.whitelist()
	def set_is_lost(self, is_lost, lost_reasons_list=None, detailed_reason=None, lost_date=None):
		self.check_permission("write")

		is_lost = cint(is_lost)

		if is_lost and self.has_sales_order_or_invoice():
			frappe.throw(_("Cannot declare as Lost because Quotation is converted to order"))

		if is_lost:
			self.set_status(update=True, status="Lost")
			self.db_set({
				'order_lost_reason': detailed_reason,
				'lost_date': getdate(lost_date),
			})
			self.lost_reasons = []
			for reason in lost_reasons_list or []:
				self.append('lost_reasons', reason)
		else:
			self.set_status(update=True, status="Open")
			self.db_set({
				'order_lost_reason': None,
				'lost_date': None,
			})
			self.lost_reasons = []

		self.update_child_table("lost_reasons")

		if self.get('opportunity') and not self.flags.from_opportunity:
			opp = frappe.get_doc("Opportunity", self.opportunity)
			opp.set_is_lost(is_lost, lost_reasons_list, detailed_reason, lost_date=lost_date)

		self.update_lead_status()
		self.update_project_quotation_status(action="set_is_lost")
		self.notify_update()

	def set_customer_name(self):
		if self.party_name and self.quotation_to == 'Customer':
			self.customer_name = frappe.get_cached_value("Customer", self.party_name, "customer_name")
		elif self.party_name and self.quotation_to == 'Lead':
			lead_name, company_name = frappe.db.get_value("Lead", self.party_name, ["lead_name", "company_name"])
			self.customer_name = company_name or lead_name

	def print_other_charges(self,docname):
		print_lst = []
		for d in self.get('taxes'):
			lst1 = []
			lst1.append(d.description)
			lst1.append(d.total)
			print_lst.append(lst1)
		return print_lst

	def on_recurring(self, reference_doc, auto_repeat_doc):
		self.valid_till = None

	def update_project_quotation_status(self, action=None):
		if not self.get("project"):
			return

		doc = frappe.get_doc("Project", self.project)

		doc.validate_project_status_for_transaction(self)
		if self.docstatus == 1:
			doc.validate_for_transaction(self)

		doc.set_pending_quotation_amount(update=True)
		doc.set_status(update=True, from_doctype=self.doctype, action=action or self.get("_action"))
		doc.notify_update()

	def set_can_notify_onload(self):
		notification_types = [
			'Quotation Delivery',
			'Quotation Reminder',
		]

		can_notify = frappe._dict()
		for notification_type in notification_types:
			can_notify[notification_type] = self.validate_notification(notification_type, throw=False)

		self.set_onload('can_notify', can_notify)

	def set_scheduled_reminder_onload(self):
		self.set_onload('scheduled_reminder', self.get_reminder_schedule())

	def get_reminder_schedule(self):
		if self.docstatus != 1 or not self.transaction_date or not automated_reminder_enabled():
			return None

		reminder_date = get_reminder_date_from_quotation_date(self.transaction_date)
		quotations_for_reminder = get_quotations_for_reminder_notification(reminder_date, quotations=self.name)

		if self.name in quotations_for_reminder:
			return get_quotation_reminders_scheduled_time(reminder_date)

	def validate_notification(self, notification_type=None, child_doctype=None, child_name=None, throw=False):
		if notification_type in ("Quotation Delivery", "Quotation Reminder"):
			# Must be submitted
			if self.docstatus != 1:
				if throw:
					frappe.throw(_("Cannot send notification because Quotation is not submitted"))
				return False

		# Must be Open
		if notification_type in ("Quotation Delivery", "Quotation Reminder"):
			if self.status != "Open":
				if throw:
					frappe.throw(_("Cannot send {0} notification because Quotation status is not 'Open'").format(
						notification_type
					))
				return False

		return True

	def send_quotation_reminder_notification(self):
		self.run_method("notify_quotation_reminder")


@frappe.whitelist()
def make_sales_order(source_name, target_doc=None):
	quotation = frappe.db.get_value("Quotation", source_name, ["transaction_date", "valid_till"], as_dict = 1)
	if quotation.valid_till and (quotation.valid_till < quotation.transaction_date or quotation.valid_till < getdate(nowdate())):
		frappe.throw(_("Validity period of this quotation has ended."))
	return _make_sales_order(source_name, target_doc=target_doc)


def _make_sales_order(
	source_name,
	target_doc=None,
	ignore_permissions=False,
	skip_item_mapping=False,
	skip_postprocess=False,
):
	def postprocess(source, target):
		customer = get_customer_from_quotation(source)
		if customer:
			target.customer = customer.name
			target.customer_name = customer.customer_name

		if source.referral_sales_partner:
			target.sales_partner = source.referral_sales_partner
			target.commission_rate = frappe.get_value('Sales Partner', source.referral_sales_partner, 'commission_rate')

		target.ignore_pricing_rule = 1
		target.flags.ignore_permissions = ignore_permissions
		target.run_method("postprocess_after_mapping")

	mapping = {
		"Quotation": {
			"doctype": "Sales Order",
			"validation": {
				"docstatus": ["=", 1]
			},
			"field_map": {
				"remarks": "remarks"
			},
			"field_no_map": [
				"group_same_items",
			],
		},
		"Sales Taxes and Charges": {
			"doctype": "Sales Taxes and Charges",
			"add_if_empty": True
		},
		"Sales Team": {
			"doctype": "Sales Team",
			"add_if_empty": True
		},
		"Payment Schedule": {
			"doctype": "Payment Schedule",
			"add_if_empty": True
		}
	}

	if not skip_item_mapping:
		mapping["Quotation Item"] = get_item_mapper_for_sales_order()

	return get_mapped_doc("Quotation", source_name, mapping, target_doc,
		postprocess=postprocess if not skip_postprocess else None,
		ignore_permissions=ignore_permissions)


def get_item_mapper_for_sales_order():
	def update_item(obj, target, source_parent, target_parent):
		pass

	return {
		"doctype": "Sales Order Item",
		"field_map": {
			"parent": "quotation",
			"name": "quotation_item",
			"service_template": "service_template",
			"service_template_detail": "service_template_detail",
		},
		"postprocess": update_item,
	}


def set_expired_status():
	frappe.db.sql("""
		UPDATE `tabQuotation`
		SET `status` = 'Expired'
		WHERE `status` = 'Open' AND `valid_till` < %s AND `docstatus` = 1
	""", getdate())


@frappe.whitelist()
def set_as_approved(name):
	doc = frappe.get_doc("Quotation", name)
	doc.check_permission("write")
	doc.set_status(update=True, status="Approved")
	doc.notify_update()


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None):
	return _make_sales_invoice(source_name, target_doc)


def _make_sales_invoice(source_name, target_doc=None, ignore_permissions=False):
	def set_missing_values(source, target):
		customer = get_customer_from_quotation(source)
		if customer:
			target.customer = customer.name
			target.customer_name = customer.customer_name

		target.ignore_pricing_rule = 1
		target.flags.ignore_permissions = ignore_permissions
		target.run_method("postprocess_after_mapping")

	def update_item(source, target, source_parent, target_parent):
		target.project = source_parent.get('project')
		target.cost_center = None
		target.depreciation_percentage = None

		if target_parent:
			target_parent.adjust_rate_for_claim_item(source, target)

	doclist = get_mapped_doc("Quotation", source_name, {
			"Quotation": {
				"doctype": "Sales Invoice",
				"validation": {
					"docstatus": ["=", 1]
				},
				"field_no_map": [
					"has_stin",
					"group_same_items",
				],
				"field_map": {
					"remarks": "remarks"
				}
			},
			"Quotation Item": {
				"doctype": "Sales Invoice Item",
				"field_map": {
					"parent": "quotation",
					"name": "quotation_item",
				},
				"postprocess": update_item
			},
			"Sales Taxes and Charges": {
				"doctype": "Sales Taxes and Charges",
				"add_if_empty": True
			},
			"Sales Team": {
				"doctype": "Sales Team",
				"add_if_empty": True
			}
		}, target_doc, set_missing_values, ignore_permissions=ignore_permissions)

	return doclist


@frappe.whitelist()
def get_previous_order_details(sales_order):
	out = frappe._dict({"previous_grand_total": 0, "previous_quotation": ""})
	if not sales_order:
		return out

	details = frappe.db.get_value("Sales Order", sales_order, fieldname=["grand_total", "rounded_total"], as_dict=1)
	if not details:
		frappe.throw(_("Sales Order {0} does not exist").format(sales_order))

	out.previous_grand_total = flt(details.rounded_total) or flt(details.grand_total)

	quotations = frappe.db.sql_list("""
		select distinct i.quotation
		from `tabSales Order Item` i
		inner join `tabQuotation` qtn on qtn.name = i.quotation
		where i.parent = %s
		order by qtn.transaction_date, qtn.creation
	""", sales_order)

	out.previous_quotation = ", ".join(quotations)

	return out


def get_customer_from_quotation(quotation):
	if quotation and quotation.get('party_name'):
		if quotation.get('quotation_to') == 'Lead':
			customer = get_customer_from_lead(quotation.get("party_name"), throw=True)
			return frappe.get_cached_doc("Customer", customer)

		elif quotation.get('quotation_to') == 'Customer':
			return frappe.get_cached_doc("Customer", quotation.get("party_name"))


def send_quotation_reminder_notifications():
	if not automated_reminder_enabled():
		return

	# Do not send until reminder scheduled time has passed
	now_dt = now_datetime()
	notification_date = getdate(now_dt)
	notification_dt = get_quotation_reminders_scheduled_time(notification_date)
	if now_dt < notification_dt:
		return

	last_scheduled = get_notification_last_scheduled(
		"Quotation",
		"",
		"Quotation Reminder",
		"",
	)
	if last_scheduled and getdate(last_scheduled) >= notification_date:
		return

	quotations_to_remind = get_quotations_for_reminder_notification(notification_date)

	for name in quotations_to_remind:
		try:
			doc = frappe.get_doc("Quotation", name)
			doc.send_quotation_reminder_notification()
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title="Error sending Quotation Reminder Notification",
				reference_doctype="Quotation",
				reference_name=name,
			)
			frappe.db.commit()

	set_notification_last_scheduled(
		"Quotation",
		"",
		"Quotation Reminder",
		"",
		now_dt=now_dt,
	)


def automated_reminder_enabled():
	return has_notification(
		"Quotation",
		notification_type="Quotation Reminder",
		trigger_method="notify_quotation_reminder",
	)


def get_quotations_for_reminder_notification(reminder_date=None, quotations=None):
	settings = frappe.get_cached_doc("Selling Settings", None)

	now_dt = now_datetime()
	reminder_date = getdate(reminder_date)
	reminder_dt = get_quotation_reminders_scheduled_time(reminder_date)

	remind_days_after = cint(settings.quotation_reminder_days_after)
	if remind_days_after <= 0:
		return []

	quotation_date = add_days(reminder_date, -remind_days_after)

	if quotations and isinstance(quotations, str):
		quotations = [quotations]

	quotations_condition = " and qtn.name in %(quotations)s" if quotations else ""

	quotations_to_remind = frappe.db.sql_list(f"""
		select qtn.name
		from `tabQuotation` qtn
		left join `tabNotification Count` n on n.reference_doctype = 'Quotation' and n.reference_name = qtn.name
			and n.notification_type = 'Quotation Reminder'
		where qtn.docstatus = 1
			and qtn.status = 'Open'
			and qtn.transaction_date = %(quotation_date)s
			and n.last_scheduled_dt is null
			and n.last_sent_dt is null
			{quotations_condition}
	""", {
		'quotation_date': quotation_date,
		'quotations': quotations,
	})

	return quotations_to_remind


def get_quotation_reminders_scheduled_time(reminder_date=None):
	settings = frappe.get_cached_doc("Selling Settings", None)

	reminder_date = getdate(reminder_date)
	reminder_time = settings.quotation_reminder_time or get_time("00:00:00")
	reminder_dt = combine_datetime(reminder_date, reminder_time)

	return reminder_dt


def get_reminder_date_from_quotation_date(quotation_date):
	settings = frappe.get_cached_doc("Selling Settings", None)

	quotation_date = getdate(quotation_date)

	remind_days_after = cint(settings.quotation_reminder_days_after)
	if remind_days_after < 0:
		remind_days_after = 0

	reminder_date = add_days(quotation_date, remind_days_after)
	return reminder_date
