# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import flt, cint, add_days, getdate
from frappe.utils import get_datetime_str
from erpnext import get_default_company


def get_root_of(doctype):
	"""Get root element of a DocType with a tree structure"""
	result = frappe.db.sql_list("""select name from `tab%s`
		where lft=1 and rgt=(select max(rgt) from `tab%s` where docstatus < 2)""" %
		(doctype, doctype))
	return result[0] if result else None


def get_ancestors_of(doctype, name):
	"""Get ancestor elements of a DocType with a tree structure"""
	lft, rgt = frappe.db.get_value(doctype, name, ["lft", "rgt"])
	result = frappe.db.sql_list("""select name from `tab%s`
		where lft<%s and rgt>%s order by lft desc""" % (doctype, "%s", "%s"), (lft, rgt))
	return result or []


def before_tests():
	frappe.clear_cache()
	# complete setup if missing
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete
	if not frappe.get_list("Company"):
		setup_complete({
			"currency"			:"USD",
			"full_name"			:"Test User",
			"company_name"		:"Wind Power LLC",
			"timezone"			:"America/New_York",
			"company_abbr"		:"WP",
			"industry"			:"Manufacturing",
			"country"			:"United States",
			"fy_start_date"		:"2011-01-01",
			"fy_end_date"		:"2011-12-31",
			"language"			:"english",
			"company_tagline"	:"Testing",
			"email"				:"test@erpnext.com",
			"password"			:"test",
			"chart_of_accounts" : "Standard",
			"domains"			: ["Manufacturing"],
		})

	frappe.db.sql("delete from `tabLeave Allocation`")
	frappe.db.sql("delete from `tabLeave Application`")
	frappe.db.sql("delete from `tabSalary Slip`")
	frappe.db.sql("delete from `tabItem Price`")

	enable_all_roles_and_domains()

	frappe.db.commit()


@frappe.whitelist()
def get_exchange_rate(
	from_currency,
	to_currency,
	transaction_date=None,
	args=None,
	provider=None,
):
	if not from_currency or not to_currency:
		return None
	if from_currency == to_currency:
		return 1.0

	transaction_date = getdate(transaction_date)

	# Get Currency Exchange record first
	if not provider:
		exchange_rate = get_exchange_rate_from_currency_exchange(
			from_currency,
			to_currency,
			transaction_date,
			args=args,
		)
		if exchange_rate:
			return exchange_rate

	# Then fetch from provider
	exchange_rate = get_exchange_rate_from_provider(
		from_currency,
		to_currency,
		transaction_date,
		provider=provider,
	)
	return exchange_rate or 0.0


def get_exchange_rate_from_currency_exchange(
	from_currency,
	to_currency,
	transaction_date=None,
	args=None,
):
	if not from_currency or not to_currency:
		return None
	if from_currency == to_currency:
		return 1.0

	settings = frappe.get_cached_doc("Accounts Settings", None)
	allow_stale_rates = settings.get("allow_stale")

	transaction_date = getdate(transaction_date)
	filters = [
		["date", "<=", get_datetime_str(transaction_date)],
		["from_currency", "=", from_currency],
		["to_currency", "=", to_currency]
	]

	if args == "for_buying":
		filters.append(["for_buying", "=", "1"])
	elif args == "for_selling":
		filters.append(["for_selling", "=", "1"])

	if not allow_stale_rates:
		stale_days = cint(settings.get("stale_days"))
		checkpoint_date = add_days(transaction_date, -stale_days)
		filters.append(["date", ">", checkpoint_date])

	entries = frappe.get_all(
		"Currency Exchange",
		fields=["exchange_rate"],
		filters=filters,
		order_by="date desc",
		limit=1
	)
	if entries:
		return flt(entries[0].exchange_rate)


def get_exchange_rate_from_provider(
	from_currency,
	to_currency,
	transaction_date=None,
	provider=None,
):
	if not from_currency or not to_currency:
		return None
	if not provider:
		provider = frappe.get_cached_value("Accounts Settings", None, "default_currency_exchange_provider")
	if not provider:
		return None

	transaction_date = getdate(transaction_date)

	exchange_rate_providers = frappe.get_hooks("exchange_rate_providers") or {}
	get_exchange_rate_method = exchange_rate_providers.get(provider)
	get_exchange_rate_method = get_exchange_rate_method[0] if get_exchange_rate_method else None
	if not get_exchange_rate_method:
		return None

	cache_key = f"exchange_rate:{provider}:{from_currency}:{to_currency}:{transaction_date}"
	exchange_rate = flt(frappe.cache.get_value(cache_key, shared=True))
	if exchange_rate > 0:
		return flt(exchange_rate)

	try:
		exchange_rate = frappe.call(
			get_exchange_rate_method,
			from_currency,
			to_currency,
			transaction_date=transaction_date,
			provider=provider,
		)
	except Exception:
		frappe.log_error(title=f"Get Exchange Rate from {provider}")
		frappe.msgprint(_("Unable to find exchange rate for {0} to {1} for key date {2}. Please enter exchange rate manually").format(
			from_currency, to_currency, transaction_date
		))

	if flt(exchange_rate) > 0:
		frappe.cache.set_value(cache_key, exchange_rate, expires_in_sec=6 * 60 * 60, shared=True)

	return exchange_rate


def get_exchange_rate_providers():
	exchange_rate_providers = frappe.get_hooks("exchange_rate_providers") or {}
	return list(exchange_rate_providers.keys())


def enable_all_roles_and_domains():
	""" enable all roles and domain for testing """
	# add all roles to users
	domains = frappe.get_all("Domain")
	if not domains:
		return

	from frappe.desk.page.setup_wizard.setup_wizard import add_all_roles_to
	frappe.get_single('Domain Settings').set_active_domains(\
		[d.name for d in domains])
	add_all_roles_to('Administrator')


def insert_record(records):
	for r in records:
		doc = frappe.new_doc(r.get("doctype"))
		doc.update(r)
		try:
			doc.insert(ignore_permissions=True)
		except frappe.DuplicateEntryError as e:
			# pass DuplicateEntryError and continue
			if e.args and e.args[0]==doc.doctype and e.args[1]==doc.name:
				# make sure DuplicateEntryError is for the exact same doc and not a related doc
				pass
			else:
				raise


def welcome_email():
	site_name = get_default_company() or "ERPNext"
	title = _("Welcome to {0}").format(site_name)
	return title
