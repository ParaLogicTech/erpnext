# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
import erpnext
import frappe.defaults
from frappe import _
from frappe.utils import nowdate, cstr, flt, cint, getdate, formatdate, get_number_format_info
from erpnext.stock.utils import get_stock_value_on
from erpnext.stock import get_warehouse_account_map
from erpnext.accounts.doctype.account.account import get_account_currency  # do not remove


class FiscalYearError(frappe.ValidationError):
	pass


@frappe.whitelist()
def get_fiscal_year(date=None, fiscal_year=None, label="Date", verbose=1, company=None, as_dict=False):
	return get_fiscal_years(date, fiscal_year, label, verbose, company, as_dict=as_dict)[0]


def get_fiscal_years(transaction_date=None, fiscal_year=None, label="Date", verbose=1, company=None, as_dict=False):
	fiscal_years = frappe.cache.hget("fiscal_years", company) or []

	if not fiscal_years:
		# if year start date is 2012-04-01, year end date should be 2013-03-31 (hence subdate)
		cond = ""
		if fiscal_year:
			cond += " and fy.name = {0}".format(frappe.db.escape(fiscal_year))
		if company:
			cond += """
				and (not exists (select name
					from `tabFiscal Year Company` fyc
					where fyc.parent = fy.name)
				or exists(select company
					from `tabFiscal Year Company` fyc
					where fyc.parent = fy.name
					and fyc.company=%(company)s)
				)
			"""

		fiscal_years = frappe.db.sql("""
			select
				fy.name, fy.year_start_date, fy.year_end_date
			from
				`tabFiscal Year` fy
			where
				disabled = 0 {0}
			order by
				fy.year_start_date desc""".format(cond), {
				"company": company
			}, as_dict=True)

		frappe.cache.hset("fiscal_years", company, fiscal_years)

	if transaction_date:
		transaction_date = getdate(transaction_date)

	for fy in fiscal_years:
		matched = False
		if fiscal_year and fy.name == fiscal_year:
			matched = True

		if (transaction_date and getdate(fy.year_start_date) <= transaction_date
			and getdate(fy.year_end_date) >= transaction_date):
			matched = True

		if matched:
			if as_dict:
				return (fy,)
			else:
				return ((fy.name, fy.year_start_date, fy.year_end_date),)

	error_msg = _("""{0} {1} not in any active Fiscal Year.""").format(label, formatdate(transaction_date))
	if verbose==1: frappe.msgprint(error_msg)
	raise FiscalYearError(error_msg)


def validate_fiscal_year(date, fiscal_year, company, label="Date", doc=None):
	years = [f[0] for f in get_fiscal_years(date, label=_(label), company=company)]
	if fiscal_year not in years:
		if doc:
			doc.fiscal_year = years[0]
		else:
			frappe.throw(_("{0} '{1}' not in Fiscal Year {2}").format(label, formatdate(date), fiscal_year))


@frappe.whitelist()
def get_balance_on(
	account=None,
	date=None,
	party_type=None,
	party=None,
	company=None,
	in_account_currency=True,
	cost_center=None,
	ignore_account_permission=False,
):
	in_account_currency = cint(in_account_currency)

	account_doc = frappe.get_cached_doc("Account", account) if account else None
	report_type = account_doc.report_type if account_doc else None

	try:
		year_start_date = get_fiscal_year(date, company=company, verbose=0)[1]
	except FiscalYearError:
		if getdate(date) > getdate():
			# if fiscal year not found and the date is greater than today
			# get fiscal year for today's date and its corresponding year start date
			year_start_date = get_fiscal_year(getdate(), verbose=1)[1]
		else:
			# this indicates that it is a date older than any existing fiscal year.
			# hence, assuming balance as 0.0
			return 0.0

	conditions = []

	if date:
		conditions.append("posting_date <= {0}".format(frappe.db.escape(cstr(date))))

	if company:
		conditions.append("gle.company = {0}".format(frappe.db.escape(company)))

	if account:
		if not frappe.flags.ignore_account_permission and not ignore_account_permission:
			account_doc.check_permission("read")

		# for pnl accounts, get balance within a fiscal year
		if report_type == "Profit and Loss":
			conditions.append("posting_date >= '{0}' and voucher_type != 'Period Closing Voucher'".format(
				year_start_date
			))

		# different filter for group and ledger - improved performance
		if account_doc.is_group:
			conditions.append("""exists (
				select name
				from `tabAccount` ac
				where ac.name = gle.account and ac.lft >= {0} and ac.rgt <= {1}
			)""".format(account_doc.lft, account_doc.rgt))

			# If group and currency same as company,
			# always return balance based on debit and credit in company currency
			if account_doc.account_currency == frappe.get_cached_value('Company',  account_doc.company,  "default_currency"):
				in_account_currency = False
		else:
			conditions.append("gle.account = {0}".format(frappe.db.escape(account)))

	if party_type and party:
		conditions.append("gle.party_type = {0} and gle.party = {1}".format(
			frappe.db.escape(party_type), frappe.db.escape(party)
		))

	if cost_center and report_type == "Profit and Loss":
		cost_center_doc = frappe.get_cached_doc("Cost Center", cost_center)
		if cost_center_doc.is_group:
			conditions.append("""exists (
				select 1 from `tabCost Center` cc
				where cc.name = gle.cost_center and cc.lft >= {0} and cc.rgt <= {1}
			)""".format(cost_center_doc.lft, cost_center_doc.rgt))
		else:
			conditions.append("gle.cost_center = {0}".format(frappe.db.escape(cost_center)))

	if account or (party_type and party):
		if in_account_currency:
			select_field = "sum(debit_in_account_currency) - sum(credit_in_account_currency)"
		else:
			select_field = "sum(debit) - sum(credit)"

		conditions_str = " and ".join(conditions)

		balance = frappe.db.sql(f"""
			SELECT {select_field}
			FROM `tabGL Entry` gle
			WHERE {conditions_str}
		""")
		balance = flt(balance[0][0]) if balance else 0.0
		return balance


def get_balance_on_voucher(
	voucher_type,
	voucher_no,
	party_type,
	party,
	account,
	company=None,
	dr_or_cr=None,
	include_original_references=False
):
	if not dr_or_cr:
		if erpnext.get_party_account_type(party_type) == 'Receivable':
			dr_or_cr = "debit_in_account_currency - credit_in_account_currency"
		else:
			dr_or_cr = "credit_in_account_currency - debit_in_account_currency"

	if not account and company:
		account_condition = "company = {0}".format(frappe.db.escape(company))
	else:
		if isinstance(account, list):
			account = [frappe.db.escape(d) for d in account]
			account_condition = "account in ({0})".format(", ".join(account))
		else:
			account_condition = "account = {0}".format(frappe.db.escape(account))

	original_reference_cond = ""
	if include_original_references:
		original_reference_cond = "or (original_against_voucher_type = %(voucher_type)s and original_against_voucher = %(voucher_no)s)"

	res = frappe.db.sql(f"""
		select ifnull(sum({dr_or_cr}), 0)
		from `tabGL Entry`
		where
			party_type = %(party_type)s
			and party = %(party)s
			and {account_condition}
			and (
				(
					voucher_type = %(voucher_type)s
					and voucher_no = %(voucher_no)s
					and (against_voucher is null or against_voucher = '')
				)
				or (
					against_voucher_type = %(voucher_type)s
					and against_voucher = %(voucher_no)s
				)
				{original_reference_cond}
			)
	""", {
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"party_type": party_type,
		"party": party,
	})

	return flt(res[0][0]) if res else 0.0


def get_count_on(account, fieldname, date):
	cond = []
	if date:
		cond.append("posting_date <= %s" % frappe.db.escape(cstr(date)))
	else:
		# get balance of all entries that exist
		date = nowdate()

	try:
		year_start_date = get_fiscal_year(date, verbose=0)[1]
	except FiscalYearError:
		if getdate(date) > getdate(nowdate()):
			# if fiscal year not found and the date is greater than today
			# get fiscal year for today's date and its corresponding year start date
			year_start_date = get_fiscal_year(nowdate(), verbose=1)[1]
		else:
			# this indicates that it is a date older than any existing fiscal year.
			# hence, assuming balance as 0.0
			return 0.0

	if account:
		acc = frappe.get_doc("Account", account)

		if not frappe.flags.ignore_account_permission:
			acc.check_permission("read")

		# for pl accounts, get balance within a fiscal year
		if acc.report_type == 'Profit and Loss':
			cond.append("posting_date >= '%s' and voucher_type != 'Period Closing Voucher'" \
				% year_start_date)

		# different filter for group and ledger - improved performance
		if acc.is_group:
			cond.append("""exists (
				select name from `tabAccount` ac where ac.name = gle.account
				and ac.lft >= %s and ac.rgt <= %s
			)""" % (acc.lft, acc.rgt))
		else:
			cond.append("""gle.account = %s """ % (frappe.db.escape(account, percent=False), ))

		entries = frappe.db.sql("""
			SELECT name, posting_date, account, party_type, party,debit,credit,
				voucher_type, voucher_no, against_voucher_type, against_voucher
			FROM `tabGL Entry` gle
			WHERE {0}""".format(" and ".join(cond)), as_dict=True)

		count = 0
		for gle in entries:
			if fieldname not in ('invoiced_amount','payables'):
				count += 1
			else:
				dr_or_cr = "debit" if fieldname == "invoiced_amount" else "credit"
				cr_or_dr = "credit" if fieldname == "invoiced_amount" else "debit"
				select_fields = "ifnull(sum(credit-debit),0)" \
					if fieldname == "invoiced_amount" else "ifnull(sum(debit-credit),0)"

				if ((not gle.against_voucher) or (gle.against_voucher_type in ["Sales Order", "Purchase Order"]) or
				(gle.against_voucher==gle.voucher_no and gle.get(dr_or_cr) > 0)):
					payment_amount = frappe.db.sql("""
						SELECT {0}
						FROM `tabGL Entry` gle
						WHERE docstatus < 2 and posting_date <= %(date)s and against_voucher = %(voucher_no)s
						and party = %(party)s and name != %(name)s"""
						.format(select_fields),
						{"date": date, "voucher_no": gle.voucher_no,
							"party": gle.party, "name": gle.name})[0][0]

					outstanding_amount = flt(gle.get(dr_or_cr)) - flt(gle.get(cr_or_dr)) - payment_amount
					currency_precision = get_currency_precision() or 2
					if abs(flt(outstanding_amount)) >= 1.0/10**currency_precision:
						count += 1

		return count


@frappe.whitelist()
def add_ac(args=None):
	from frappe.desk.treeview import make_tree_args

	if not args:
		args = frappe.local.form_dict

	args.doctype = "Account"
	args = make_tree_args(**args)

	ac = frappe.new_doc("Account")

	if args.get("ignore_permissions"):
		ac.flags.ignore_permissions = True
		args.pop("ignore_permissions")

	ac.update(args)

	if not ac.parent_account:
		ac.parent_account = args.get("parent")

	ac.old_parent = ""
	ac.freeze_account = "No"
	if cint(ac.get("is_root")):
		ac.parent_account = None
		ac.flags.ignore_mandatory = True

	ac.insert()

	return ac.name


@frappe.whitelist()
def add_cc(args=None):
	from frappe.desk.treeview import make_tree_args

	if not args:
		args = frappe.local.form_dict

	args.doctype = "Cost Center"
	args = make_tree_args(**args)

	if args.parent_cost_center == args.company:
		args.parent_cost_center = "{0} - {1}".format(args.parent_cost_center,
			frappe.get_cached_value('Company',  args.company,  'abbr'))

	cc = frappe.new_doc("Cost Center")
	cc.update(args)

	if not cc.parent_cost_center:
		cc.parent_cost_center = args.get("parent")

	cc.old_parent = ""
	cc.insert()
	return cc.name


def get_advance_against_voucher_types():
	return frappe.get_hooks("advance_against_voucher_types")


@frappe.whitelist()
def get_company_default(company, fieldname):
	value = frappe.get_cached_value('Company',  company,  fieldname)

	if not value:
		frappe.throw(_("Please set default {0} in Company {1}")
			.format(frappe.get_meta("Company").get_label(fieldname), company))

	return value


def fix_total_debit_credit():
	vouchers = frappe.db.sql("""select voucher_type, voucher_no,
		sum(debit) - sum(credit) as diff
		from `tabGL Entry`
		group by voucher_type, voucher_no
		having sum(debit) != sum(credit)""", as_dict=1)

	for d in vouchers:
		if abs(d.diff) > 0:
			dr_or_cr = d.voucher_type == "Sales Invoice" and "credit" or "debit"

			frappe.db.sql("""update `tabGL Entry` set %s = %s + %s
				where voucher_type = %s and voucher_no = %s and %s > 0 limit 1""" %
				(dr_or_cr, dr_or_cr, '%s', '%s', '%s', dr_or_cr),
				(d.diff, d.voucher_type, d.voucher_no))


def get_stock_and_account_balance(account=None, posting_date=None, company=None):
	if not posting_date: posting_date = nowdate()

	warehouse_account = get_warehouse_account_map(company)

	account_balance = get_balance_on(account, posting_date, in_account_currency=False, ignore_account_permission=True)

	related_warehouses = [wh for wh, wh_details in warehouse_account.items()
		if wh_details.account == account and not wh_details.is_group]

	total_stock_value = 0.0
	for warehouse in related_warehouses:
		value = get_stock_value_on(warehouse, posting_date)
		total_stock_value += value

	precision = frappe.get_precision("Journal Entry Account", "debit_in_account_currency")
	return flt(account_balance, precision), flt(total_stock_value, precision), related_warehouses


def get_currency_precision():
	precision = cint(frappe.db.get_default("currency_precision"))
	if not precision:
		number_format = frappe.db.get_default("number_format") or "#,###.##"
		precision = get_number_format_info(number_format)[2]

	return precision


def get_stock_rbnb_difference(posting_date, company):
	stock_items = frappe.db.sql_list("""select distinct item_code
		from `tabStock Ledger Entry` where company=%s""", company)

	pr_valuation_amount = frappe.db.sql("""
		select sum(pr_item.valuation_rate * pr_item.qty * pr_item.conversion_factor)
		from `tabPurchase Receipt Item` pr_item, `tabPurchase Receipt` pr
		where pr.name = pr_item.parent and pr.docstatus=1 and pr.company=%s
		and pr.posting_date <= %s and pr_item.item_code in (%s)""" %
		('%s', '%s', ', '.join(['%s']*len(stock_items))), tuple([company, posting_date] + stock_items))[0][0]

	pi_valuation_amount = frappe.db.sql("""
		select sum(pi_item.valuation_rate * pi_item.qty * pi_item.conversion_factor)
		from `tabPurchase Invoice Item` pi_item, `tabPurchase Invoice` pi
		where pi.name = pi_item.parent and pi.docstatus=1 and pi.company=%s
		and pi.posting_date <= %s and pi_item.item_code in (%s)""" %
		('%s', '%s', ', '.join(['%s']*len(stock_items))), tuple([company, posting_date] + stock_items))[0][0]

	# Balance should be
	stock_rbnb = flt(pr_valuation_amount, 2) - flt(pi_valuation_amount, 2)

	# Balance as per system
	stock_rbnb_account = "Stock Received But Not Billed - " + frappe.get_cached_value('Company',  company,  "abbr")
	sys_bal = get_balance_on(stock_rbnb_account, posting_date, in_account_currency=False)

	# Amount should be credited
	return flt(stock_rbnb) + flt(sys_bal)


def get_held_invoices(party_type, party):
	"""
	Returns a list of names Purchase Invoices for the given party that are on hold
	"""
	held_invoices = []

	if party_type == "Supplier":
		today_date = getdate()
		held_invoices = frappe.db.sql_list("""
			select name
			from `tabPurchase Invoice`
			where release_date IS NOT NULL and release_date > %s
		""", today_date)

	return held_invoices


def get_account_name(account_type=None, root_type=None, is_group=None, account_currency=None, company=None):
	"""return account based on matching conditions"""
	return frappe.db.get_value("Account", {
		"account_type": account_type or '',
		"root_type": root_type or '',
		"is_group": is_group or 0,
		"account_currency": account_currency or frappe.defaults.get_defaults().currency,
		"company": company or frappe.defaults.get_defaults().company
	}, "name")


@frappe.whitelist()
def get_companies():
	"""get a list of companies based on permission"""
	return [d.name for d in frappe.get_list("Company", fields=["name"],
		order_by="name")]


@frappe.whitelist()
def get_children(doctype, parent, company, is_root=False):
	from erpnext.accounts.report.financial_statements import sort_accounts

	parent_fieldname = 'parent_' + doctype.lower().replace(' ', '_')
	fields = [
		'name as value',
		'is_group as expandable'
	]
	filters = [['docstatus', '<', 2]]

	filters.append(['ifnull(`{0}`,"")'.format(parent_fieldname), '=', '' if is_root else parent])

	if is_root:
		fields += ['root_type', 'report_type', 'account_currency'] if doctype == 'Account' else []
		filters.append(['company', '=', company])

	else:
		fields += ['root_type', 'account_currency'] if doctype == 'Account' else []
		fields += [parent_fieldname + ' as parent']

	acc = frappe.get_list(doctype, fields=fields, filters=filters)

	if doctype == 'Account':
		sort_accounts(acc, is_root, key="value")
		company_currency = frappe.get_cached_value('Company',  company,  "default_currency")
		for each in acc:
			each["company_currency"] = company_currency
			each["balance"] = flt(get_balance_on(each.get("value"), in_account_currency=False, company=company))

			if each.account_currency != company_currency:
				each["balance_in_account_currency"] = flt(get_balance_on(each.get("value"), company=company))

	return acc


@frappe.whitelist()
def update_cost_center(docname, cost_center_name, cost_center_number, company, merge):
	'''
		Renames the document by adding the number as a prefix to the current name and updates
		all transaction where it was present.
	'''
	validate_field_number("Cost Center", docname, cost_center_number, company, "cost_center_number")

	if cost_center_number:
		frappe.db.set_value("Cost Center", docname, "cost_center_number", cost_center_number.strip())
	else:
		frappe.db.set_value("Cost Center", docname, "cost_center_number", "")

	frappe.db.set_value("Cost Center", docname, "cost_center_name", cost_center_name.strip())

	new_name = get_autoname_with_number(cost_center_number, cost_center_name, docname, company)
	if docname != new_name:
		frappe.rename_doc("Cost Center", docname, new_name, force=1, merge=merge)
		return new_name


def validate_field_number(doctype_name, docname, number_value, company, field_name):
	''' Validate if the number entered isn't already assigned to some other document. '''
	if number_value:
		filters = {field_name: number_value, "name": ["!=", docname]}
		if company:
			filters["company"] = company

		doctype_with_same_number = frappe.db.get_value(doctype_name, filters)

		if doctype_with_same_number:
			frappe.throw(_("{0} Number {1} is already used in {2} {3}")
				.format(doctype_name, number_value, doctype_name.lower(), doctype_with_same_number))


def get_autoname_with_number(number_value, doc_title, name, company):
	''' append title with prefix as number and suffix as company's abbreviation separated by '-' '''
	if name:
		name_split=name.split("-")
		parts = [doc_title.strip(), name_split[len(name_split)-1].strip()]
	else:
		abbr = frappe.get_cached_value('Company',  company,  ["abbr"], as_dict=True)
		parts = [doc_title.strip(), abbr.abbr]
	if cstr(number_value).strip():
		parts.insert(0, cstr(number_value).strip())
	return ' - '.join(parts)


@frappe.whitelist()
def get_coa(doctype, parent, is_root, chart=None):
	from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import build_tree_from_json

	# add chart to flags to retrieve when called from expand all function
	chart = chart if chart else frappe.flags.chart
	frappe.flags.chart = chart

	parent = None if parent==_('All Accounts') else parent
	accounts = build_tree_from_json(chart) # returns alist of dict in a tree render-able form

	# filter out to show data for the selected node only
	accounts = [d for d in accounts if d['parent_account']==parent]

	return accounts


def get_allow_cost_center_in_entry_of_bs_account():
	def generator():
		return cint(frappe.db.get_value('Accounts Settings', None, 'allow_cost_center_in_entry_of_bs_account'))
	return frappe.local_cache("get_allow_cost_center_in_entry_of_bs_account", (), generator, regenerate_if_none=True)


def get_allow_project_in_entry_of_bs_account():
	def generator():
		return cint(frappe.db.get_value('Accounts Settings', None, 'allow_project_in_entry_of_bs_account'))
	return frappe.local_cache("get_allow_project_in_entry_of_bs_account", (), generator, regenerate_if_none=True)


def get_stock_accounts(company):
	filters = {
		"account_type": "Stock"
	}
	if company:
		filters["company"] = company

	return frappe.get_all("Account", filters=filters)


def parse_naming_series_variable(doc, variable):
	if variable == "FY":
		date = doc.get("posting_date") or doc.get("transaction_date") or getdate()
		return get_fiscal_year(date=date, company=doc.get("company"))[0]
	elif variable == "CO":
		company = doc.get("company") or erpnext.get_default_company()
		return frappe.get_cached_value('Company', company, 'abbr')
	elif variable == "BR":
		return frappe.get_cached_value('Branch', doc.get('branch'), 'abbreviation')


def format_account(account, field=None, default=None):
	if account:
		account_number = frappe.get_cached_value("Account", account, "account_number")
		account_name = frappe.get_cached_value("Account", account, "account_name") or account

		if field == "account_number":
			return cstr(account_number)
		elif field == "account_name":
			return cstr(account_name)
		elif account_number:
			return f"{account_number} - {account_name}"
		else:
			return account_name
	else:
		return cstr(default)


def format_cost_center(cost_center, default=None):
	if cost_center:
		return frappe.get_cached_value("Cost Center", cost_center, "cost_center_name") or cost_center
	else:
		return cstr(default)


def get_additional_sales_invoice_no_fields():
	fields = frappe.get_hooks("additional_sales_invoice_no_fields") or []
	fields = [f for f in fields if frappe.get_meta("Sales Invoice").has_field(f)]
	return fields
