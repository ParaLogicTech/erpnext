# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import cint, today, formatdate, get_timestamp
from frappe.cache_manager import clear_defaults_cache
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.utils.nestedset import NestedSet
import frappe.defaults
import os
import json


class Company(NestedSet):
	nsm_parent_field = 'parent_company'

	def onload(self):
		load_address_and_contact(self, "company")
		self.get("__onload")["transactions_exist"] = self.get_transactions_exist()

	def validate(self):
		self.update_default_account = True if self.is_new() else False
		self.validate_abbr()
		self.validate_default_accounts()
		self.validate_default_warehouses()
		self.validate_currency()
		self.validate_coa_input()
		self.validate_perpetual_inventory()
		self.check_country_change()
		self.set_chart_of_accounts()

	def get_transactions_exist(self):
		ledger_doctypes = ["GL Entry", "Stock Ledger Entry"]
		transaction_doctypes = [
			"Sales Order",
			"Quotation",
			"Purchase Order",
			"Supplier Quotation",
		]

		for doctype in transaction_doctypes + ledger_doctypes:
			filters = {"company": self.name}
			if doctype not in ledger_doctypes:
				filters["docstatus"] = 1

			if frappe.db.exists(doctype, filters):
				return True

		return False

	def validate_abbr(self):
		if not self.abbr:
			self.abbr = "".join([c[0] for c in self.company_name.split()]).upper()

		self.abbr = self.abbr.strip()
		if not self.abbr:
			frappe.throw(_("Company Abbreviation is mandatory"))

		existing_company = frappe.db.get_value("Company", {"abbr": self.abbr, "name": ["!=", self.name]})
		if existing_company:
			frappe.throw(_("Abbreviation {0} is already used by Company {1}").format(
				frappe.bold(self.abbr), frappe.get_desk_link("Company", existing_company)
			))

	@frappe.whitelist()
	def create_default_tax_template(self):
		from erpnext.setup.setup_wizard.operations.taxes_setup import create_sales_tax
		create_sales_tax({
			'country': self.country,
			'company_name': self.name
		})

	def validate_default_accounts(self):
		account_fields = [df for df in self.meta.fields if df.fieldtype == "Link" and df.options == "Account"]
		for df in account_fields:
			self.validate_company_account(self.get(df.fieldname), df)

		for d in self.advance_tax_accounts:
			self.validate_company_account(d.account_head, d.meta.get_field("account_head"))

	def validate_company_account(self, account, df):
		if not account:
			return

		account_details = frappe.db.get_value("Account", account, ["company", "is_group"], as_dict=1)
		if not account_details:
			frappe.throw(_("{0} {1} does not exist").format(_(df.label), frappe.bold(account)))

		if account_details.company != self.name:
			frappe.throw(_("{0} {1} does not belong to Company {2}").format(
				_(df.label), frappe.bold(account), self.name,
			))
		if account_details.is_group:
			frappe.throw(_("{0} {1} is a Group Account and cannot be a default account").format(
				_(df.label), frappe.bold(account),
			))

	def validate_default_warehouses(self):
		warehouse_fields = [df for df in self.meta.fields if df.fieldtype == "Link" and df.options == "Warehouse"]
		for df in warehouse_fields:
			self.validate_company_warehouse(self.get(df.fieldname), df)

	def validate_company_warehouse(self, warehouse, df):
		if not warehouse:
			return

		warehouse_details = frappe.db.get_value("Warehouse", warehouse, ["company", "is_group"], as_dict=1)
		if not warehouse_details:
			frappe.throw(_("{0} {1} does not exist").format(_(df.label), frappe.bold(warehouse)))

		if warehouse_details.company != self.name:
			frappe.throw(_("{0} {1} does not belong to Company {2}").format(
				_(df.label), frappe.bold(warehouse), self.name,
			))
		if warehouse_details.is_group:
			frappe.throw(_("{0} {1} is a Group Warehouse and cannot be a default warehouse").format(
				_(df.label), frappe.bold(warehouse),
			))

	def validate_currency(self):
		if self.is_new():
			return

		self.previous_default_currency = self.db_get("default_currency")
		if (
			self.default_currency
			and self.previous_default_currency
			and self.default_currency != self.previous_default_currency
			and self.get_transactions_exist()
		):
			frappe.throw(_("Cannot change company's default currency, because there are existing transactions. Transactions must be cancelled to change the default currency."))

	def on_update(self):
		super().on_update()

		if not frappe.flags.ignore_chart_of_accounts and not frappe.db.exists("Account", {"company": self.name}):
			frappe.flags.country_change = True
			self.create_default_accounts()
			self.create_default_warehouses()

		if frappe.flags.country_change:
			install_country_fixtures(self.name)
			self.create_default_tax_template()

		if not frappe.db.exists("Department", {"company": self.name}):
			from erpnext.setup.setup_wizard.operations.install_fixtures import install_post_company_fixtures
			install_post_company_fixtures(frappe._dict({'company_name': self.name}))

		if not frappe.db.exists("Cost Center", {"company": self.name, "is_group": 0}):
			self.create_default_cost_center()

		if not frappe.flags.ignore_chart_of_accounts:
			self.set_default_accounts()
			if self.default_cash_account:
				self.set_mode_of_payment_account()

		if self.default_currency:
			frappe.db.set_value("Currency", self.default_currency, "enabled", 1)

		if hasattr(frappe.local, 'enable_perpetual_inventory') and \
			self.name in frappe.local.enable_perpetual_inventory:
			frappe.local.enable_perpetual_inventory[self.name] = self.enable_perpetual_inventory

		frappe.clear_cache()

	def create_default_warehouses(self):
		for wh_detail in [
			{"warehouse_name": _("All Warehouses"), "is_group": 1},
			{"warehouse_name": _("Stores"), "is_group": 0},
		]:
			if not frappe.db.exists("Warehouse", "{0} - {1}".format(wh_detail["warehouse_name"], self.abbr)):
				warehouse = frappe.get_doc({
					"doctype":"Warehouse",
					"warehouse_name": wh_detail["warehouse_name"],
					"is_group": wh_detail["is_group"],
					"company": self.name,
					"parent_warehouse": "{0} - {1}".format(_("All Warehouses"), self.abbr) if not wh_detail["is_group"] else ""
				})
				warehouse.flags.ignore_permissions = True
				warehouse.flags.ignore_mandatory = True
				warehouse.insert()

	def create_default_accounts(self):
		from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import create_charts
		frappe.local.flags.ignore_root_company_validation = True
		create_charts(self.name, self.chart_of_accounts, self.existing_company)

	def validate_coa_input(self):
		if self.create_chart_of_accounts_based_on == "Existing Company":
			self.chart_of_accounts = None
			if not self.existing_company:
				frappe.throw(_("Please select Existing Company for creating Chart of Accounts"))

		else:
			self.existing_company = None
			self.create_chart_of_accounts_based_on = "Standard Template"
			if not self.chart_of_accounts:
				self.chart_of_accounts = "Standard"

	def validate_perpetual_inventory(self):
		if not self.get("__islocal"):
			if cint(self.enable_perpetual_inventory) == 1 and not self.default_inventory_account:
				frappe.msgprint(_("Set default inventory account for perpetual inventory"),
					alert=True, indicator='orange')

	def check_country_change(self):
		frappe.flags.country_change = False
		if not self.is_new() and self.country != self.db_get("country"):
			frappe.flags.country_change = True

	def set_chart_of_accounts(self):
		''' If parent company is set, chart of accounts will be based on that company '''
		if self.parent_company:
			self.create_chart_of_accounts_based_on = "Existing Company"
			self.existing_company = self.parent_company

	def set_default_accounts(self):
		if not self.get("update_default_account"):
			return

		default_accounts_map = {
			"default_cash_account": "Cash",
			"default_bank_account": "Bank",
			"round_off_account": "Round Off",
			"accumulated_depreciation_account": "Accumulated Depreciation",
			"depreciation_expense_account": "Depreciation",
			"capital_work_in_progress_account": "Capital Work in Progress",
			"asset_received_but_not_billed": "Asset Received But Not Billed",
			"expenses_included_in_asset_valuation": "Expenses Included In Asset Valuation"
		}

		if self.enable_perpetual_inventory:
			default_accounts_map.update({
				"stock_received_but_not_billed": "Stock Received But Not Billed",
				"default_inventory_account": "Stock",
				"stock_adjustment_account": "Stock Adjustment",
				"expenses_included_in_valuation": "Expenses Included In Valuation",
				"default_expense_account": "Cost of Goods Sold"
			})

		for default_account in default_accounts_map:
			self._set_default_account(default_account, default_accounts_map.get(default_account))

		if not self.default_income_account:
			income_account = frappe.db.get_value("Account", {
				"account_name": _("Sales"), "company": self.name, "is_group": 0
			})
			if not income_account:
				income_account = frappe.db.get_value("Account", {
					"account_name": _("Sales Account"), "company": self.name, "is_group": 0
				})
			if income_account:
				self.db_set("default_income_account", income_account)

		if not self.default_receivable_account:
			default_receivable_account = frappe.db.get_value("Account", {
				"company": self.name, "is_group": 0, "account_type": "Receivable",
			})
			if default_receivable_account:
				self.db_set("default_receivable_account", default_receivable_account)

		if not self.default_payable_account:
			default_payable_account = frappe.db.get_value("Account", {
				"account_name": _("Creditors"), "company": self.name, "is_group": 0, "account_type": "Payable",
			})
			if not default_payable_account:
				default_payable_account = frappe.db.get_value("Account", {
					"account_name": _("Accounts Payable"), "company": self.name, "is_group": 0, "account_type": "Payable",
				})
			if not default_payable_account:
				default_payable_account = frappe.db.get_value("Account", {
					"company": self.name, "is_group": 0, "account_type": "Payable",
				})

			if default_payable_account:
				self.db_set("default_payable_account", default_payable_account)

		if not self.default_payroll_payable_account:
			payroll_payable_account = frappe.db.get_value("Account", {
				"account_name": _("Payroll Payable"), "company": self.name, "is_group": 0,
			})
			if payroll_payable_account:
				self.db_set("default_payroll_payable_account", payroll_payable_account)

		if not self.default_letter_of_credit_account:
			default_letter_of_credit_account = frappe.db.get_value("Account", {
				"account_name": _("Letters of Credit"), "company": self.name, "is_group": 0
			})
			if default_letter_of_credit_account:
				self.db_set("default_letter_of_credit_account", default_letter_of_credit_account)

		if not self.default_employee_advance_account:
			employe_advance_account = frappe.db.get_value("Account", {
				"account_name": _("Employee Advances"), "company": self.name, "is_group": 0
			})

			self.db_set("default_employee_advance_account", employe_advance_account)

		if not self.temporary_opening_account:
			temporary_opening_account = frappe.db.get_value("Account", {
				"account_name": _("Temporary Opening"), "company": self.name, "is_group": 0
			})
			if temporary_opening_account:
				self.db_set("temporary_opening_account", temporary_opening_account)

		if not self.write_off_account:
			write_off_acct = frappe.db.get_value("Account", {
				"account_name": _("Write Off"), "company": self.name, "is_group": 0
			})
			if write_off_acct:
				self.db_set("write_off_account", write_off_acct)

		if not self.exchange_gain_loss_account:
			exchange_gain_loss_acct = frappe.db.get_value("Account",
				{"account_name": _("Exchange Gain/Loss"), "company": self.name, "is_group": 0})
			if exchange_gain_loss_acct:
				self.db_set("exchange_gain_loss_account", exchange_gain_loss_acct)

		if not self.disposal_account:
			disposal_acct = frappe.db.get_value("Account",
				{"account_name": _("Gain/Loss on Asset Disposal"), "company": self.name, "is_group": 0})
			if disposal_acct:
				self.db_set("disposal_account", disposal_acct)

	def _set_default_account(self, fieldname, account_type):
		if self.get(fieldname):
			return

		account = frappe.db.get_value("Account", {
			"account_type": account_type, "is_group": 0, "company": self.name
		})
		if account:
			self.db_set(fieldname, account)

	def set_mode_of_payment_account(self):
		cash_mop = frappe.db.get_value('Mode of Payment', {'type': 'Cash'}, 'name')
		if (
			cash_mop
			and self.default_cash_account
			and not frappe.db.get_value('Mode of Payment Account', {'company': self.name, 'parent': cash_mop})
		):
			mode_of_payment = frappe.get_doc('Mode of Payment', cash_mop)
			mode_of_payment.append('accounts', {
				'company': self.name,
				'default_account': self.default_cash_account,
			})
			mode_of_payment.save(ignore_permissions=True)

	def create_default_cost_center(self):
		cc_list = [
			{
				'cost_center_name': self.name,
				'company': self.name,
				'is_group': 1,
				'parent_cost_center': None
			},
			{
				'cost_center_name': _('Main'),
				'company': self.name,
				'is_group': 0,
				'parent_cost_center': self.name + ' - ' + self.abbr
			},
		]
		for cc in cc_list:
			cc.update({"doctype": "Cost Center"})
			cc_doc = frappe.get_doc(cc)
			cc_doc.flags.ignore_permissions = True

			if cc.get("cost_center_name") == self.name:
				cc_doc.flags.ignore_mandatory = True
			cc_doc.insert()

		self.db_set("cost_center", _("Main") + " - " + self.abbr)
		self.db_set("round_off_cost_center", _("Main") + " - " + self.abbr)
		self.db_set("depreciation_cost_center", _("Main") + " - " + self.abbr)

	def after_rename(self, olddn, newdn, merge=False):
		self.db_set("company_name", newdn)

		frappe.db.sql("""
			update `tabDefaultValue`
			set defvalue = %s
			where defkey = 'Company' and defvalue = %s
		""", (newdn, olddn))

		clear_defaults_cache()

	def abbreviate(self):
		self.abbr = ''.join([c[0].upper() for c in self.company_name.split()])

	def on_trash(self):
		"""
			Trash accounts and cost centers for this company if no gl entry exists
		"""
		NestedSet.validate_if_child_exists(self)
		frappe.utils.nestedset.update_nsm(self)

		has_gle = frappe.db.exists("GL Entry", {"company": self.name})
		has_sle = frappe.db.exists("Stock Ledger Entry", {"company": self.name})

		if not has_gle:
			frappe.db.sql("""
				delete from `tabBudget Account`
				where exists(
					select name from tabBudget where name=`tabBudget Account`.parent and company = %s
				)
			""", self.name)

			for doctype in ["Account", "Cost Center", "Budget", "Party Account"]:
				frappe.db.sql("delete from `tab{0}` where company = %s".format(doctype), self.name)

		if not has_sle:
			frappe.db.sql("""delete from `tabWarehouse` where company=%s""", self.name)

		frappe.defaults.clear_default("company", value=self.name)
		for doctype in ["Mode of Payment Account", "Item Default Rule"]:
			frappe.db.sql("delete from `tab{0}` where company = %s".format(doctype), self.name)

		# clear default accounts, warehouses from item
		warehouses = frappe.db.sql_list("select name from tabWarehouse where company=%s", self.name)
		if warehouses:
			frappe.db.sql("""
				delete from `tabItem Reorder`
				where warehouse in %s
			""", [warehouses])

		# reset default company
		frappe.db.sql("""
			update `tabSingles`
			set value = ''
			where doctype = 'Global Defaults' and field = 'default_company' and value = %s
		""", self.name)

		# reset default company
		frappe.db.sql("""
			update `tabSingles`
			set value = ''
			where doctype = 'Chart of Accounts Importer' and field = 'company'
			and value = %s
		""", self.name)

		# delete BOMs
		boms = frappe.db.sql_list("select name from tabBOM where company=%s", self.name)
		if boms:
			frappe.db.sql("delete from tabBOM where company=%s", self.name)
			for dt in ("BOM Operation", "BOM Item", "BOM Scrap Item", "BOM Explosion Item", "BOM Additional Cost"):
				frappe.db.sql("delete from `tab%s` where parent in (%s)"""
					% (dt, ', '.join(['%s']*len(boms))), tuple(boms))

		frappe.db.sql("delete from tabEmployee where company=%s", self.name)
		frappe.db.sql("delete from tabDepartment where company=%s", self.name)
		frappe.db.sql("delete from `tabTax Withholding Account` where company=%s", self.name)

		frappe.db.sql("delete from `tabSales Taxes and Charges Template` where company=%s", self.name)
		frappe.db.sql("delete from `tabPurchase Taxes and Charges Template` where company=%s", self.name)


@frappe.whitelist()
def enqueue_replace_abbr(company, old, new):
	frappe.only_for("System Manager")

	kwargs = dict(company=company, old=old, new=new, queue="long")
	frappe.enqueue('erpnext.setup.doctype.company.company.replace_abbr', **kwargs)


def replace_abbr(company, old, new):
	new = new.strip()
	if not new:
		frappe.throw(_("Abbr can not be blank or space"))

	frappe.only_for("System Manager")

	frappe.db.set_value("Company", company, "abbr", new)

	def _rename_record(doc):
		parts = doc[0].rsplit(" - ", 1)
		if len(parts) == 1 or parts[1].lower() == old.lower():
			frappe.rename_doc(dt, doc[0], parts[0] + " - " + new, force=True)

	def _rename_records(dt):
		# rename is expensive so let's be economical with memory usage
		doc = (d for d in frappe.db.sql("select name from `tab%s` where company=%s" % (dt, '%s'), company))
		for d in doc:
			_rename_record(d)

	for dt in [
		"Warehouse",
		"Account",
		"Cost Center",
		"Department",
		"Sales Taxes and Charges Template",
		"Purchase Taxes and Charges Template",
	]:
		_rename_records(dt)


def get_name_with_abbr(name, company):
	company_abbr = frappe.get_cached_value('Company',  company,  "abbr")
	parts = name.split(" - ")

	if parts[-1].lower() != company_abbr.lower():
		parts.append(company_abbr)

	return " - ".join(parts)


def install_country_fixtures(company, country=None):
	company_doc = frappe.get_doc("Company", company)
	if not country:
		country = company_doc.country

	path = frappe.get_app_path('erpnext', 'regional', frappe.scrub(country))
	if os.path.exists(path.encode("utf-8")):
		try:
			module_name = "erpnext.regional.{0}.setup.setup".format(frappe.scrub(country))
			frappe.get_attr(module_name)(company_doc, False)
		except Exception:
			frappe.log_error(title="Failed to setup country defaults")
			frappe.throw(_("Failed to setup defaults for country {0}").format(
				frappe.bold(company_doc.country)
			))


def update_company_current_month_sales(company):
	current_month_year = formatdate(today(), "MM-yyyy")

	results = frappe.db.sql('''
		SELECT
			SUM(base_grand_total) AS total,
			DATE_FORMAT(`posting_date`, '%m-%Y') AS month_year
		FROM
			`tabSales Invoice`
		WHERE
			DATE_FORMAT(`posting_date`, '%m-%Y') = '{current_month_year}'
			AND docstatus = 1
			AND company = {company}
		GROUP BY
			month_year
	'''.format(current_month_year=current_month_year, company=frappe.db.escape(company)),
		as_dict = True)

	monthly_total = results[0]['total'] if len(results) > 0 else 0

	frappe.db.set_value("Company", company, "total_monthly_sales", monthly_total)


def update_company_monthly_sales(company):
	'''Cache past year monthly sales of every company based on sales invoices'''
	from frappe.utils.goal import get_monthly_results
	import json
	filter_str = "company = {0} and status != 'Draft' and docstatus=1".format(frappe.db.escape(company))
	month_to_value_dict = get_monthly_results("Sales Invoice", "base_grand_total",
		"posting_date", filter_str, "sum")

	frappe.db.set_value("Company", company, "sales_monthly_history", json.dumps(month_to_value_dict))


def update_transactions_annual_history(company, commit=False):
	transactions_history = get_all_transactions_annual_history(company)
	frappe.db.set_value("Company", company, "transactions_annual_history", json.dumps(transactions_history))

	if commit:
		frappe.db.commit()


def cache_companies_monthly_sales_history():
	companies = [d['name'] for d in frappe.get_list("Company")]
	for company in companies:
		update_company_monthly_sales(company)
		update_transactions_annual_history(company)
	frappe.db.commit()


@frappe.whitelist()
def get_children(doctype, parent=None, company=None, is_root=False):
	if parent == None or parent == "All Companies":
		parent = ""

	return frappe.db.sql("""
		select
			name as value,
			is_group as expandable
		from
			`tab{doctype}` comp
		where
			ifnull(parent_company, "")={parent}
		""".format(
			doctype = doctype,
			parent=frappe.db.escape(parent)
		), as_dict=1)


@frappe.whitelist()
def add_node():
	from frappe.desk.treeview import make_tree_args
	args = frappe.form_dict
	args = make_tree_args(**args)

	if args.parent_company == 'All Companies':
		args.parent_company = None

	frappe.get_doc(args).insert()


def get_all_transactions_annual_history(company):
	out = {}

	items = frappe.db.sql('''
		select transaction_date, count(*) as count

		from (
			select name, transaction_date, company
			from `tabQuotation`

			UNION ALL

			select name, transaction_date, company
			from `tabSales Order`

			UNION ALL

			select name, posting_date as transaction_date, company
			from `tabDelivery Note`

			UNION ALL

			select name, posting_date as transaction_date, company
			from `tabSales Invoice`

			UNION ALL

			select name, creation as transaction_date, company
			from `tabIssue`

			UNION ALL

			select name, creation as transaction_date, company
			from `tabProject`
		) t

		where
			company=%s
			and
			transaction_date > date_sub(curdate(), interval 1 year)

		group by
			transaction_date
			''', (company), as_dict=True)

	for d in items:
		timestamp = get_timestamp(d["transaction_date"])
		out.update({ timestamp: d["count"] })

	return out


def get_timeline_data(doctype, name):
	'''returns timeline data based on linked records in dashboard'''
	out = {}
	date_to_value_dict = {}

	history = frappe.get_cached_value('Company',  name,  "transactions_annual_history")

	try:
		date_to_value_dict = json.loads(history) if history and '{' in history else None
	except ValueError:
		date_to_value_dict = None

	if date_to_value_dict is None:
		update_transactions_annual_history(name, True)
		history = frappe.get_cached_value('Company',  name,  "transactions_annual_history")
		return json.loads(history) if history and '{' in history else {}

	return date_to_value_dict


@frappe.whitelist()
def get_default_company_address(name, sort_key="is_primary_address", existing_address=None):
	if sort_key not in ["is_shipping_address", "is_primary_address"]:
		return None

	out = frappe.db.sql(
		""" SELECT
			addr.name, addr.%s
		FROM
			`tabAddress` addr, `tabDynamic Link` dl
		WHERE
			dl.parent = addr.name and dl.link_doctype = 'Company' and
			dl.link_name = %s and ifnull(addr.disabled, 0) = 0
		"""
		% (sort_key, "%s"),
		(name),
	)  # nosec

	if existing_address:
		if existing_address in [d[0] for d in out]:
			return existing_address

	if out:
		return min(out, key=lambda x: x[1])[0]  # find min by sort_key
	else:
		return None
