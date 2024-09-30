# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.model.naming import set_name_by_naming_series
from frappe import _, msgprint, throw
import frappe.defaults
from frappe.utils import flt, cint, cstr, today, clean_whitespace, getdate, now_datetime, get_time, combine_datetime, add_years
from frappe.desk.reportview import build_match_conditions, get_filters_cond
from erpnext.utilities.transaction_base import TransactionBase
from erpnext.accounts.party import validate_party_accounts, get_dashboard_info, get_address_display
from frappe.contacts.address_and_contact import load_address_and_contact, delete_contact_and_address
from frappe.contacts.doctype.contact.contact import get_default_contact
from frappe.contacts.doctype.address.address import get_default_address
from erpnext.vehicles.doctype.vehicle_log.vehicle_log import get_customer_vehicle_selector_data
from frappe.model.rename_doc import update_linked_doctypes
from frappe.model.mapper import get_mapped_doc
from frappe.core.doctype.sms_settings.sms_settings import enqueue_template_sms

primary_address_fields = [
	{'customer_field': 'address_line1', 'address_field': 'address_line1'},
	{'customer_field': 'address_line2', 'address_field': 'address_line2'},
	{'customer_field': 'address_line3', 'address_field': 'address_line3'},
	{'customer_field': 'city', 'address_field': 'city'},
	{'customer_field': 'state', 'address_field': 'state'},
	{'customer_field': 'country', 'address_field': 'country'},
	{'customer_field': 'pincode', 'address_field': 'pincode'},
]
primary_contact_fields = [
	{'customer_field': 'salutation', 'contact_field': 'salutation'},
	{'customer_field': 'contact_first_name', 'contact_field': 'first_name', 'default_from': 'customer_name'},
	{'customer_field': 'contact_middle_name', 'contact_field': 'middle_name'},
	{'customer_field': 'contact_last_name', 'contact_field': 'last_name'},
	{'customer_field': 'mobile_no', 'contact_field': 'mobile_no'},
	{'customer_field': 'mobile_no_2', 'contact_field': 'mobile_no_2'},
	{'customer_field': 'phone_no', 'contact_field': 'phone'},
	{'customer_field': 'email_id', 'contact_field': 'email_id'}
]


class Customer(TransactionBase):
	def get_feed(self):
		return self.customer_name

	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)
		self.load_dashboard_info()

		if 'Vehicles' in frappe.get_active_domains() and not self.is_new():
			self.set_onload('customer_vehicle_selector_data', get_customer_vehicle_selector_data(customer=self.name))

	def load_dashboard_info(self):
		info = get_dashboard_info(self.doctype, self.name, self.loyalty_program)
		self.set_onload('dashboard_info', info)

	def autoname(self):
		cust_master_name = frappe.defaults.get_global_default('cust_master_name')
		if cust_master_name == 'Customer Name':
			self.name = self.get_customer_name()
		else:
			set_name_by_naming_series(self)

	def get_customer_name(self):
		if frappe.db.get_value("Customer", self.customer_name):
			count = frappe.db.sql("""select ifnull(MAX(CAST(SUBSTRING_INDEX(name, ' ', -1) AS UNSIGNED)), 0) from tabCustomer
				 where name like %s""", "%{0} - %".format(self.customer_name), as_list=1)[0][0]
			count = cint(count) + 1
			return "{0} - {1}".format(self.customer_name, cstr(count))

		return self.customer_name

	def validate(self):
		self.flags.is_new_doc = self.is_new()

		self.customer_name = clean_whitespace(self.customer_name)
		validate_party_accounts(self)
		self.validate_credit_limit_on_change()
		self.set_loyalty_program()
		self.check_customer_group_change()
		self.validate_default_bank_account()

		self.validate_tax_id()
		self.validate_mobile_no()

		# set loyalty program tier
		if frappe.db.exists('Customer', self.name):
			customer = frappe.get_doc('Customer', self.name)
			if self.loyalty_program == customer.loyalty_program and not self.loyalty_program_tier:
				self.loyalty_program_tier = customer.loyalty_program_tier

		if self.sales_team:
			if sum([flt(member.allocated_percentage) or 0 for member in self.sales_team]) != 100:
				frappe.throw(_("Total contribution percentage should be equal to 100"))

	def after_insert(self):
		if self.lead_name:
			self.update_customer_in_lead()
			self.assign_lead_address_contact()

	def on_update(self):
		self.validate_name_with_customer_group()

		self.update_primary_contact()
		self.update_primary_address()

		self.update_customer_groups()

	def check_customer_group_change(self):
		frappe.flags.customer_group_changed = False

		if not self.get('__islocal'):
			if self.customer_group != frappe.db.get_value('Customer', self.name, 'customer_group'):
				frappe.flags.customer_group_changed = True

	def validate_default_bank_account(self):
		if self.default_bank_account:
			is_company_account = frappe.db.get_value('Bank Account', self.default_bank_account, 'is_company_account')
			if not is_company_account:
				frappe.throw(_("{0} is not a company bank account").format(frappe.bold(self.default_bank_account)))

	def validate_tax_id(self):
		from frappe.regional.pakistan import validate_ntn_cnic_strn, validate_duplicate_tax_id
		validate_ntn_cnic_strn(self.tax_id, self.tax_cnic, self.tax_strn)

		cnic_throw = frappe.db.get_single_value('Selling Settings', 'validate_duplicate_customer_cnic')
		ntn_throw = frappe.db.get_single_value('Selling Settings', 'validate_duplicate_customer_ntn')
		role_allowed_to_duplicate_customer_ntn = frappe.db.get_single_value('Selling Settings', 'role_allowed_to_duplicate_customer_ntn')

		if cnic_throw:
			cnic_throw = self.restrict_duplicate_field('tax_cnic')

		if ntn_throw:
			ntn_throw = self.restrict_duplicate_field('tax_id')

		if role_allowed_to_duplicate_customer_ntn in frappe.get_roles():
			ntn_throw = False

		exclude = None if self.is_new() else self.name
		validate_duplicate_tax_id("Customer", "tax_id", self.tax_id, exclude=exclude, throw=ntn_throw)
		validate_duplicate_tax_id("Customer", "tax_cnic", self.tax_cnic, exclude=exclude, throw=cnic_throw)
		validate_duplicate_tax_id("Customer", "tax_strn", self.tax_strn, exclude=exclude, throw=False)

	def restrict_duplicate_field(self, fieldname):
		if self.is_new():
			return True

		old_value = frappe.db.get_value("Customer", self.name, fieldname)

		if self.get(fieldname) != old_value:
			return True

	def validate_mobile_no(self):
		from frappe.regional.pakistan import validate_mobile_pakistan
		validate_mobile_pakistan(self.mobile_no)
		validate_mobile_pakistan(self.mobile_no_2)

	def update_customer_groups(self):
		ignore_doctypes = ["Lead", "Opportunity", "POS Profile", "Tax Rule", "Pricing Rule"]
		if frappe.flags.customer_group_changed:
			update_linked_doctypes('Customer', self.name, 'Customer Group',
				self.customer_group, ignore_doctypes)

	def update_primary_contact(self):
		push_or_pull = None

		if not self.customer_primary_contact:
			self.customer_primary_contact = get_default_contact("Customer", self.name)
			push_or_pull = "pull"

		contact = None
		data_provided = any([self.get(d['customer_field']) for d in primary_contact_fields])

		if not self.customer_primary_contact and data_provided:
			contact = make_contact(self)
			push_or_pull = "pull"

		elif self.customer_primary_contact:
			contact = frappe.get_doc("Contact", self.customer_primary_contact)
			if not push_or_pull:
				push_or_pull = "push" if data_provided else "pull"

		if contact:
			if self.flags.pull_contact or push_or_pull == "pull":
				self.pull_primary_contact(contact)

			elif push_or_pull == "push":
				self.push_primary_contact(contact)
				self.pull_primary_contact(contact)

	def pull_primary_contact(self, contact):
		to_set = {'customer_primary_contact': contact.name}
		for d in primary_contact_fields:
			if self.meta.has_field(d['customer_field']):
				to_set[d['customer_field']] = contact.get(d['contact_field'])

		self.update(to_set)
		frappe.db.set_value("Customer", self.name, to_set, None,
			notify=cint(self.flags.pull_contact), update_modified=cint(self.flags.pull_contact))

	def push_primary_contact(self, contact):
		data_changed = any([cstr(self.get(d['customer_field'])) != cstr(contact.get(d['contact_field']))
			for d in primary_contact_fields])

		if data_changed:
			for field in primary_contact_fields:
				if not field.get('custom_setter'):
					value = self.get(field['customer_field'])
					if not value and field.get('default_from'):
						value = self.get(field.get('default_from'))

					contact.set(field['contact_field'], value)

			contact.flags.from_linked_document = ("Customer", self.name)
			contact.save(ignore_permissions=True)

	def update_primary_address(self):
		push_or_pull = None

		if not self.customer_primary_address:
			self.customer_primary_address = get_default_address("Customer", self.name)
			push_or_pull = "pull"

		address = None
		data_provided = any([self.get(d['customer_field']) for d in primary_address_fields])

		if not self.customer_primary_address and data_provided and self.address_line1:
			address = make_address(self)
			push_or_pull = "pull"

		elif self.customer_primary_address:
			address = frappe.get_doc("Address", self.customer_primary_address)
			if not push_or_pull:
				push_or_pull = "push" if data_provided else "pull"

		if address:
			if self.flags.pull_address or push_or_pull == "pull":
				self.pull_primary_address(address)

			elif push_or_pull == "push":
				self.push_primary_address(address)
				self.pull_primary_address(address)

	def pull_primary_address(self, address):
		to_set = {'customer_primary_address': address.name, 'primary_address': get_address_display(address.as_dict())}
		for d in primary_address_fields:
			if self.meta.has_field(d['customer_field']):
				to_set[d['customer_field']] = address.get(d['address_field'])

		self.update(to_set)
		frappe.db.set_value("Customer", self.name, to_set, None,
			notify=cint(self.flags.pull_address), update_modified=cint(self.flags.pull_address))

	def push_primary_address(self, address):
		data_changed = any([cstr(self.get(d['customer_field'])) != cstr(address.get(d['address_field']))
			for d in primary_address_fields])

		if data_changed:
			for field in primary_address_fields:
				if not field.get('custom_setter'):
					value = self.get(field['customer_field'])
					if not value and field.get('default_from'):
						value = self.get(field.get('default_from'))

					address.set(field['address_field'], value)

			address.flags.from_linked_document = ("Customer", self.name)
			address.save(ignore_permissions=True)

	def update_customer_in_lead(self):
		'''If Customer created from Lead, update lead status to "Converted"
		update Customer link in Quotation, Opportunity'''
		if self.lead_name:
			new_lead = frappe.get_doc("Lead", self.lead_name)
			new_lead.update_customer_reference(self.name)
			new_lead.notify_update()

	def assign_lead_address_contact(self):
		if self.lead_name:
			# Assign Addresses
			address_names = frappe.get_all('Dynamic Link', filters={
				"parenttype": "Address",
				"link_doctype": "Lead",
				"link_name": self.lead_name
			}, fields=["parent as name"])

			for address_name in address_names:
				address = frappe.get_doc('Address', address_name.get('name'))
				if not address.has_link('Customer', self.name):
					address.append('links', dict(link_doctype='Customer', link_name=self.name))
					address.save()

			# Assign Contacts
			contact_names = frappe.get_all('Dynamic Link', filters={
				"parenttype": "Contact",
				"link_doctype": "Lead",
				"link_name": self.lead_name
			}, fields=["parent as name"])

			for contact_name in contact_names:
				contact = frappe.get_doc('Contact', contact_name.get('name'))
				if not contact.has_link('Customer', self.name):
					contact.append('links', dict(link_doctype='Customer', link_name=self.name))
					contact.save()

	def validate_name_with_customer_group(self):
		if frappe.db.exists("Customer Group", self.name):
			frappe.throw(_("A Customer Group exists with same name please change the Customer name or rename the Customer Group"), frappe.NameError)

	def validate_credit_limit_on_change(self):
		if self.get("__islocal") or not self.credit_limits:
			return
		
		past_credit_limits = [d.credit_limit
			for d in frappe.db.get_all("Customer Credit Limit", filters={'parent': self.name}, fields=["credit_limit"], order_by="company")]
		
		current_credit_limits = [d.credit_limit for d in sorted(self.credit_limits, key=lambda k: k.company)]

		if past_credit_limits == current_credit_limits:
			return

		company_record = []
		for limit in self.credit_limits:
			if limit.company in company_record:
				frappe.throw(_("Credit limit is already defined for the Company {0}").format(limit.company, self.name))
			else:
				company_record.append(limit.company)

			outstanding_amt = get_customer_outstanding(self.name, limit.company)
			if flt(limit.credit_limit) < outstanding_amt:
				frappe.throw(_("""New credit limit is less than current outstanding amount for the customer. Credit limit has to be atleast {0}""").format(outstanding_amt))

	def on_trash(self):
		if self.customer_primary_contact or self.customer_primary_address:
			frappe.db.sql("""update `tabCustomer`
				set customer_primary_contact=null, customer_primary_address=null
				where name=%s""", self.name)

		delete_contact_and_address('Customer', self.name)
		self.unlink_leads()

	def unlink_leads(self):
		if self.lead_name:
			self.db_set('lead_name', None)

		customer_leads = frappe.get_all("Lead", {'customer': self.name})
		for d in customer_leads:
			doc = frappe.get_doc("Lead", d.name)
			doc.update_customer_reference(None)
			doc.notify_update()

	def after_rename(self, olddn, newdn, merge=False):
		if frappe.defaults.get_global_default('cust_master_name') == 'Customer Name':
			frappe.db.set(self, "customer_name", newdn)

	def set_loyalty_program(self):
		if self.loyalty_program: return
		loyalty_program = get_loyalty_programs(self)
		if not loyalty_program: return
		if len(loyalty_program) == 1:
			self.loyalty_program = loyalty_program[0]
		else:
			frappe.msgprint(_("Multiple Loyalty Program found for the Customer. Please select manually."))

	def get_sms_args(self, notification_type=None, child_doctype=None, child_name=None):
		return frappe._dict({
			'receiver_list': [self.mobile_no],
		})

	def validate_notification(self, notification_type=None, child_doctype=None, child_name=None, throw=False):
		if not notification_type:
			if throw:
				frappe.throw(_("Notification Type is mandatory"))
			return False

		if notification_type == "Customer Birthday":
			if not self.date_of_birth:
				if throw:
					frappe.throw(_("Cannot send Customer Birthday notification because Customer Date of Birth is not set"))
				return False

		return True

	def send_customer_birthday_notification(self):
		enqueue_template_sms(self, notification_type="Customer Birthday", allow_if_already_sent=1)


@frappe.whitelist()
def make_quotation(source_name, target_doc=None):

	def set_missing_values(source, target):
		_set_missing_values(source, target)

	target_doc = get_mapped_doc("Customer", source_name,
		{"Customer": {
			"doctype": "Quotation",
			"field_map": {
				"name":"party_name"
			}
		}}, target_doc, set_missing_values)

	target_doc.quotation_to = "Customer"
	target_doc.run_method("set_missing_values")
	target_doc.run_method("reset_taxes_and_charges")
	target_doc.run_method("calculate_taxes_and_totals")

	price_list, currency = frappe.db.get_value("Customer", source_name, ['default_price_list', 'default_currency'])
	if price_list:
		target_doc.selling_price_list = price_list
	if currency:
		target_doc.currency = currency

	return target_doc


@frappe.whitelist()
def make_opportunity(source_name, target_doc=None):
	def set_missing_values(source, target):
		_set_missing_values(source, target)

	target_doc = get_mapped_doc("Customer", source_name,
		{"Customer": {
			"doctype": "Opportunity",
			"field_map": {
				"name": "party_name",
				"doctype": "opportunity_from",
			}
		}}, target_doc, set_missing_values)

	return target_doc

def _set_missing_values(source, target):
	address = frappe.get_all('Dynamic Link', {
			'link_doctype': source.doctype,
			'link_name': source.name,
			'parenttype': 'Address',
		}, ['parent'], limit=1)

	contact = frappe.get_all('Dynamic Link', {
			'link_doctype': source.doctype,
			'link_name': source.name,
			'parenttype': 'Contact',
		}, ['parent'], limit=1)

	if address:
		target.customer_address = address[0].parent

	if contact:
		target.contact_person = contact[0].parent


@frappe.whitelist()
def get_loyalty_programs(doc):
	''' returns applicable loyalty programs for a customer '''
	from frappe.desk.treeview import get_children

	lp_details = []
	loyalty_programs = frappe.get_all("Loyalty Program",
		fields=["name", "customer_group", "customer_territory"],
		filters={"auto_opt_in": 1, "from_date": ["<=", today()],
			"ifnull(to_date, '2500-01-01')": [">=", today()]})

	for loyalty_program in loyalty_programs:
		customer_groups = [d.value for d in get_children("Customer Group", loyalty_program.customer_group)] + [loyalty_program.customer_group]
		customer_territories = [d.value for d in get_children("Territory", loyalty_program.customer_territory)] + [loyalty_program.customer_territory]

		if (not loyalty_program.customer_group or doc.customer_group in customer_groups)\
			and (not loyalty_program.customer_territory or doc.territory in customer_territories):
			lp_details.append(loyalty_program.name)

	return lp_details


def check_credit_limit(customer, company, ignore_outstanding_sales_order=False, extra_amount=0):
	customer_outstanding = get_customer_outstanding(customer, company, ignore_outstanding_sales_order)
	if extra_amount > 0:
		customer_outstanding += flt(extra_amount)

	credit_limit = get_credit_limit(customer, company)
	if credit_limit > 0 and flt(customer_outstanding) > credit_limit:
		msgprint(_("Credit limit has been crossed for customer {0} ({1}/{2})")
			.format(customer, customer_outstanding, credit_limit))

		# If not authorized person raise exception
		credit_controller = frappe.db.get_value('Accounts Settings', None, 'credit_controller')
		if not credit_controller or credit_controller not in frappe.get_roles():
			throw(_("Please contact to the user who have Sales Master Manager {0} role")
				.format(" / " + credit_controller if credit_controller else ""))


def get_customer_outstanding(customer, company, ignore_outstanding_sales_order=False, cost_center=None):
	# Outstanding based on GL Entries

	cond = ""
	if cost_center:
		lft, rgt = frappe.get_cached_value("Cost Center",
			cost_center, ['lft', 'rgt'])

		cond = """ and cost_center in (select name from `tabCost Center` where
			lft >= {0} and rgt <= {1})""".format(lft, rgt)

	outstanding_based_on_gle = frappe.db.sql("""
		select sum(debit) - sum(credit)
		from `tabGL Entry` where party_type = 'Customer'
		and party = %s and company=%s {0}""".format(cond), (customer, company))

	outstanding_based_on_gle = flt(outstanding_based_on_gle[0][0]) if outstanding_based_on_gle else 0

	# Outstanding based on Sales Order
	outstanding_based_on_so = 0.0

	# if credit limit check is bypassed at sales order level,
	# we should not consider outstanding Sales Orders, when customer credit balance report is run
	if not ignore_outstanding_sales_order:
		outstanding_based_on_so = frappe.db.sql("""
			select sum(base_grand_total*(100 - per_completed)/100)
			from `tabSales Order`
			where customer=%s and docstatus = 1 and company=%s
			and billing_status = 'To Bill' and status != 'Closed'""", (customer, company))

		outstanding_based_on_so = flt(outstanding_based_on_so[0][0]) if outstanding_based_on_so else 0.0

	# Outstanding based on Delivery Note, which are not created against Sales Order
	unmarked_delivery_note_items = frappe.db.sql("""select
			dn_item.name, dn_item.amount, dn.base_net_total, dn.base_grand_total
		from `tabDelivery Note` dn, `tabDelivery Note Item` dn_item
		where
			dn.name = dn_item.parent
			and dn.customer=%s and dn.company=%s
			and dn.docstatus = 1 and dn.status not in ('Closed', 'Stopped')
			and ifnull(dn_item.sales_order, '') = ''
			and ifnull(dn_item.sales_invoice, '') = ''
		""", (customer, company), as_dict=True)

	outstanding_based_on_dn = 0.0

	for dn_item in unmarked_delivery_note_items:
		si_amount = frappe.db.sql("""select sum(amount)
			from `tabSales Invoice Item`
			where delivery_note_item = %s and docstatus = 1""", dn_item.name)[0][0]

		if flt(dn_item.amount) > flt(si_amount) and dn_item.base_net_total:
			outstanding_based_on_dn += ((flt(dn_item.amount) - flt(si_amount)) \
				/ dn_item.base_net_total) * dn_item.base_grand_total

	return outstanding_based_on_gle + outstanding_based_on_so + outstanding_based_on_dn


def get_credit_limit(customer, company):
	credit_limit = None

	if customer:
		credit_limit = frappe.db.get_value("Customer Credit Limit",
			{'parent': customer, 'parenttype': 'Customer', 'company': company}, 'credit_limit')

		if not credit_limit:
			customer_group = frappe.get_cached_value("Customer", customer, 'customer_group')
			credit_limit = frappe.db.get_value("Customer Credit Limit",
				{'parent': customer_group, 'parenttype': 'Customer Group', 'company': company}, 'credit_limit')

	if not credit_limit:
		credit_limit = frappe.get_cached_value('Company',  company,  "credit_limit")

	return flt(credit_limit)


def make_contact(args, is_primary_contact=1):
	contact = frappe.new_doc("Contact")
	contact.update({
		'is_primary_contact': is_primary_contact,
		'links': [{
			'link_doctype': args.get('doctype'),
			'link_name': args.get('name')
		}]
	})

	if args.get('contact_first_name'):
		contact.first_name = args.get('contact_first_name')
		contact.middle_name = args.get('contact_middle_name')
		contact.last_name = args.get('contact_last_name')
	else:
		contact.first_name = args.get('customer_name') or args.get('name')

	if args.get('email_id'):
		contact.add_email(args.get('email_id'), is_primary=True)
	if args.get('mobile_no'):
		contact.add_phone(args.get('mobile_no'), is_primary_mobile_no=True)
	if args.get('mobile_no_2'):
		contact.add_phone(args.get('mobile_no_2'), is_primary_mobile_no=True)
	if args.get('phone_no'):
		contact.add_phone(args.get('phone_no'), is_primary_phone=True)

	contact.flags.from_linked_document = (args.get('doctype'), args.get('name'))
	contact.insert()

	return contact


def make_address(args, is_primary_address=1):
	reqd_fields = []
	for field in ['city', 'country']:
		if not args.get(field):
			reqd_fields.append( '<li>' + field.title() + '</li>')

	if reqd_fields:
		msg = _("Following fields are mandatory to create address:")
		frappe.throw("{0} <br><br> <ul>{1}</ul>".format(msg, '\n'.join(reqd_fields)),
			title = _("Missing Values Required"))

	address = frappe.new_doc("Address")
	address.update({
		'address_title': args.get('customer_name') or args.get('name'),
		'address_line1': args.get('address_line1'),
		'address_line2': args.get('address_line2'),
		'city': args.get('city'),
		'state': args.get('state'),
		'pincode': args.get('pincode'),
		'country': args.get('country'),
		'links': [{
			'link_doctype': args.get('doctype'),
			'link_name': args.get('name')
		}]
	})

	address.flags.from_linked_document = (args.get('doctype'), args.get('name'))
	address.insert()

	return address


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_customer_primary_contact(doctype, txt, searchfield, start, page_len, filters):
	from frappe.contacts.doctype.contact.contact import contact_query

	if not filters:
		filters = {}

	filters["link_doctype"] = "Customer"
	filters["link_name"] = filters.pop("customer", None)

	return contact_query(doctype, txt, searchfield, start, page_len, filters)


@frappe.whitelist()
def get_primary_address_details(address_name):
	doc = frappe.get_doc("Address", address_name)
	out = {'primary_address': get_address_display(doc.as_dict())}
	for field in primary_address_fields:
		out[field['customer_field']] = doc.get(field['address_field'])

	return out


@frappe.whitelist()
def get_primary_contact_details(contact_name):
	doc = frappe.get_doc("Contact", contact_name)
	out = {}
	for field in primary_contact_fields:
		out[field['customer_field']] = doc.get(field['contact_field'])

	return out


def get_timeline_data(*args, **kwargs):
	from erpnext.accounts.party import get_timeline_data
	return get_timeline_data(*args, **kwargs)


def send_customer_birthday_notifications():
	if not automated_customer_birthday_enabled():
		return

	now_dt = now_datetime()
	date_today = getdate(now_dt)

	notification_dt = get_customer_birthday_scheduled_time(date_today)
	if now_dt < notification_dt:
		return

	notification_last_sent_date = frappe.db.get_global("customer_birthday_notification_last_sent_date")
	if notification_last_sent_date and getdate(notification_last_sent_date) >= date_today:
		return

	customer_birthday_data = get_customers_for_birthday_notifications(date_today)
	for d in customer_birthday_data:
		doc = frappe.get_doc("Customer", d.name)
		doc.send_customer_birthday_notification()

	frappe.db.set_global("customer_birthday_notification_last_sent_date", date_today)


def automated_customer_birthday_enabled():
	from frappe.core.doctype.sms_settings.sms_settings import is_automated_sms_enabled
	from frappe.core.doctype.sms_template.sms_template import has_automated_sms_template

	if is_automated_sms_enabled() and has_automated_sms_template("Customer", "Customer Birthday"):
		return True
	else:
		return False


def get_customer_birthday_scheduled_time(notification_date=None):
	crm_settings = frappe.get_cached_doc("CRM Settings", None)

	notification_date = getdate(notification_date)
	notification_time = crm_settings.customer_birthday_notification_time or get_time("00:00:00")
	notification_dt = combine_datetime(notification_date, notification_time)

	return notification_dt


def get_customers_for_birthday_notifications(notification_date=None):
	notification_date = getdate(notification_date)

	customer_birthday_data = frappe.db.sql("""
		SELECT c.name, c.customer_name, c.mobile_no
		FROM `tabCustomer` c
		LEFT JOIN `tabNotification Count` nc
			ON nc.reference_doctype = 'Customer'
			AND nc.reference_name = c.name
			AND nc.notification_type = 'Customer Birthday'
			AND nc.notification_medium = 'SMS'
		WHERE day(c.date_of_birth) = %(day)s
			AND month(c.date_of_birth)= %(month)s
			AND (nc.last_scheduled_dt is null OR DATE(nc.last_scheduled_dt) != %(date_today)s)
			AND (nc.last_sent_dt is null OR DATE(nc.last_sent_dt) != %(date_today)s)
	""", {
		"day": notification_date.day,
		"month": notification_date.month,
		"date_today": notification_date
	}, as_dict=1)

	return customer_birthday_data
