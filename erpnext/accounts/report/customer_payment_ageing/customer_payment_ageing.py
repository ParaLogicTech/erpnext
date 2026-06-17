# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import erpnext
from erpnext.accounts.report.accounts_receivable.accounts_receivable import get_ageing_data
from frappe import _, scrub
from frappe.utils import getdate, flt, cint
from erpnext.accounts.utils import get_currency_precision
from erpnext.accounts.report.financial_statements import get_cost_centers_with_children


def execute(filters=None):
	return PaymentAgeingReport("Customer", filters).run()


class PaymentAgeingReport:
	def __init__(self, party_type, filters=None):
		self.filters = frappe._dict(filters or {})
		self.filters.party_type = party_type
		self.filters.party = self.filters.get(scrub(self.filters.get("party_type")))

		self.currency_precision = get_currency_precision() or 2
		self.has_cost_center = False
		self.has_branch = False
		self.has_project = False
		self.has_account_manager = False

	def run(self):
		self.validate_filters()
		self.set_show_names()

		self.get_payments_gl_data()
		self.get_invoice_voucher_data()

		rows = self.prepare_rows()
		columns = self.get_columns()

		# grouped_data = self.get_grouped_data(columns, data) # Todo grouping
		chart = None  # self.get_chart_data(data) # Todo chart?

		return columns, rows, None, chart

	def validate_filters(self):
		self.filters.from_date = getdate(self.filters.from_date)
		self.filters.to_date = getdate(self.filters.to_date)
		if self.filters.from_date > self.filters.to_date:
			frappe.throw(_("From Date must be before To Date"))

		self.validate_ageing_filter()

		if not self.filters.get("company"):
			self.filters.company = erpnext.get_default_company()

		self.company_currency = frappe.get_cached_value('Company', self.filters.company, "default_currency")
		self.account_currency = self.company_currency

		if self.filters.get('cost_center'):
			self.filters.cost_center = get_cost_centers_with_children(self.filters.get("cost_center"))

		if self.filters.get("project"):
			if isinstance(self.filters.get("project"), str):
				self.filters.project = [self.filters.project]

		if self.filters.get("sales_person"):
			sales_person = self.filters.sales_person
			self.filters.sales_person = frappe.get_all("Sales Person", filters={
				"name": ["descendants of", self.filters.sales_person]
			})
			self.filters.sales_person = set([sales_person] + [d.name for d in self.filters.sales_person])

		self.dr_or_cr = "credit" if erpnext.get_party_account_type(self.filters.party_type) == "Receivable" else "debit"
		self.reverse_dr_or_cr = "credit" if self.dr_or_cr == "debit" else "debit"

	def validate_ageing_filter(self):
		self.ageing_range = [cint(r.strip()) for r in self.filters.get('ageing_range', "").split(",") if r]
		self.ageing_range = sorted(list(set(self.ageing_range)))
		self.ageing_column_count = len(self.ageing_range) + 1

	def set_show_names(self):
		self.show_party_name = False
		if self.filters.party_type == "Customer":
			if frappe.defaults.get_global_default('cust_master_name') == "Naming Series":
				self.show_party_name = True

		if self.filters.party_type == "Supplier":
			if frappe.defaults.get_global_default('supp_master_name') == "Naming Series":
				self.show_party_name = True

	def get_payments_gl_data(self):
		select_fields = [
			"gle.posting_date as payment_date",
			"gle.voucher_type",
			"gle.voucher_no",
			"gle.party",
			"gle.debit",
			"gle.credit",
			"gle.remarks as payment_remarks",
			"gle.against_voucher_type",
			"gle.against_voucher",
			"gle.company",
			"gle.account",
			"gle.cost_center",
			"gle.project",
			"100 as allocated_percentage",
		]

		if frappe.get_meta("GL Entry").has_field("branch"):
			select_fields.append("gle.branch")

		conditions = self.get_gle_conditions()

		customer_join = ""
		supplier_join = ""

		if self.filters.party_type == "Customer":
			select_fields += [
				"cus.customer_name as party_name",
				"cus.customer_group",
				"cus.territory",
				"cus.account_manager",
			]
			customer_join = "left join `tabCustomer` cus on gle.party = cus.name"

		elif self.filters.party_type == "Supplier":
			select_fields += [
				"sup.supplier_name as party_name",
				"sup.supplier_group",
			]
			supplier_join = "left join `tabSupplier` sup on gle.party = sup.name"

		select_fields_str = ", ".join(select_fields)
		conditions_str = " and " + " and ".join(conditions) if conditions else ""

		self.payment_gles = frappe.db.sql(f"""
			select {select_fields_str}
			from `tabGL Entry` gle
			{customer_join}
			{supplier_join}
			where
				gle.party_type = %(party_type)s
				and gle.voucher_type in ('Journal Entry', 'Payment Entry')
				{conditions_str}
			order by gle.posting_date, gle.creation
		""", self.filters, as_dict=1)

	def get_gle_conditions(self):
		conditions = []

		if self.filters.exclude_unallocated:
			conditions.append("(gle.against_voucher != '' and gle.against_voucher is not null)")
		else:
			conditions.append("((gle.against_voucher != '' and gle.against_voucher is not null) or (gle.{0} - gle.{1}) > 0)".format(
				self.dr_or_cr, self.reverse_dr_or_cr
			))

		if self.filters.company:
			conditions.append("gle.company = %(company)s")

		if self.filters.from_date:
			conditions.append("gle.posting_date >= %(from_date)s")

		if self.filters.to_date:
			conditions.append("gle.posting_date <= %(to_date)s")

		if self.filters.party:
			conditions.append("gle.party = %(party)s")

		if self.filters.sales_person:
			conditions.append("""exists(select sp.name from `tabSales Team` sp
				where sp.parenttype = gle.against_voucher_type and sp.parent = gle.against_voucher and sp.sales_person in %(sales_person)s)""")

		account_type = None
		if self.filters.party_type == "Customer":
			account_type = "Receivable"
			if self.filters.get("customer_group"):
				lft, rgt = frappe.db.get_value("Customer Group", self.filters.get("customer_group"), ["lft", "rgt"])
				conditions.append("""cus.customer_group in (select name from `tabCustomer Group` where lft >= {0} and rgt <= {1})""".format(
					lft, rgt
				))

			if self.filters.get("territory"):
				lft, rgt = frappe.db.get_value("Territory", self.filters.get("territory"), ["lft", "rgt"])
				conditions.append("""cus.territory in (select name from `tabTerritory` where lft >= {0} and rgt <= {1})""".format(
					lft, rgt
				))

			if self.filters.get("account_manager"):
				lft, rgt = frappe.db.get_value("Sales Person", self.filters.get("account_manager"), ["lft", "rgt"])
				conditions.append("""cus.account_manager in (select name from `tabSales Person` where lft >= {0} and rgt <= {1})""".format(
					lft, rgt
				))

		elif self.filters.party_type == "Supplier":
			account_type = "Payable"
			if self.filters.get("supplier_group"):
				lft, rgt = frappe.db.get_value("Supplier Group", self.filters.get("supplier_group"), ["lft", "rgt"])
				conditions.append("""sup.supplier_group in (select name from `tabSupplier Group` where lft >= {0} and rgt <= {1})""".format(
					lft, rgt
				))

		if self.filters.get("account"):
			self.filters.accounts = [self.filters.get("account")]
		elif account_type:
			self.filters.accounts = frappe.get_all("Account", filters={
				"account_type": account_type, "company": self.filters.company,
			}, pluck="name")

		if self.filters.accounts:
			conditions.append("gle.account in %(accounts)s")

		return conditions

	def get_invoice_voucher_data(self):
		self.against_voucher_map = {}
		for d in self.payment_gles:
			if d.against_voucher and d.against_voucher_type:
				self.against_voucher_map.setdefault(d.against_voucher_type, set()).add(d.against_voucher)

		voucher_fields = [
			("posting_date", "invoice_date"),
			"due_date",
			("remarks", "invoice_remarks"),
			("user_remark", "invoice_user_remark"),
			"branch",
			"cost_center",
			"project",
			"territory",
			"bill_no",
			"bill_date",
		]

		self.invoice_voucher_map = {}
		for voucher_type, voucher_nos in self.against_voucher_map.items():
			self.invoice_voucher_map.setdefault(voucher_type, {})

			select_fields = []
			meta = frappe.get_meta(voucher_type)
			for f in voucher_fields:
				if isinstance(f, tuple):
					if meta.has_field(f[0]):
						select_fields.append(f"v.{f[0]} as {f[1]}")
				else:
					if meta.has_field(f):
						select_fields.append(f"v.{f}")

			if not select_fields:
				continue

			sales_team_join = ""
			if voucher_type == "Sales Invoice":
				sales_team_join = "left join `tabSales Team` sp on sp.parent = v.name"
				select_fields += [
					"GROUP_CONCAT(DISTINCT sp.sales_person SEPARATOR ', ') as sales_person",
					"sum(ifnull(sp.allocated_percentage, 100)) as allocated_percentage",
				]

			select_fields_str = ", ".join(select_fields)

			vouchers_data = frappe.db.sql(f"""
				select v.name as against_voucher, {select_fields_str}
				from `tab{voucher_type}` v
				{sales_team_join}
				where v.name in %s
				group by v.name
			""", [voucher_nos], as_dict=1)

			for d in vouchers_data:
				self.invoice_voucher_map[voucher_type][d.against_voucher] = d

	def prepare_rows(self):
		rows = []
		for gle in self.payment_gles:
			row = gle
			row.payment_amount = flt(row[self.dr_or_cr]) - flt(row[self.reverse_dr_or_cr])
			row.allocated_payment_amount = flt(flt(row.payment_amount) * flt(row.allocated_percentage) / 100)

			# Voucher details
			voucher_details = None
			if gle.against_voucher and gle.against_voucher_type:
				voucher_details = self.invoice_voucher_map.get(gle.against_voucher_type, {}).get(gle.against_voucher)

			# fallback fields from payment
			if voucher_details:
				for k, v in voucher_details.items():
					if v or isinstance(v, (int, float)):
						row[k] = v

			# Remarks
			row.invoice_remarks = row.invoice_user_remark or row.invoice_remarks

			# Ageing data
			if self.filters.ageing_based_on == "Due Date":
				invoice_ageing_date = row.due_date or row.invoice_date
			elif self.filters.ageing_based_on == "Supplier Invoice Date":
				invoice_ageing_date = row.bill_date or row.invoice_date
			else:
				invoice_ageing_date = row.invoice_date

			row["age"], ageing_data = get_ageing_data(
				self.ageing_range,
				row.payment_date,
				invoice_ageing_date,
				row.payment_amount,
			)
			for i, age_range_value in enumerate(ageing_data):
				row["range{0}".format(i + 1)] = age_range_value

			# Has
			if row.get("cost_center"):
				self.has_cost_center = True
			if row.get("branch"):
				self.has_branch = True
			if row.get("project"):
				self.has_project = True
			if row.get("account_manager"):
				self.has_account_manager = True

			# Post Filter
			if self.filters.cost_center:
				if not row.cost_center or row.cost_center not in self.filters.cost_center:
					continue
			if self.filters.branch:
				if not row.branch or row.branch != self.filters.branch:
					continue
			if self.filters.project:
				if not row.project or row.project != self.filters.project:
					continue

			rows.append(row)

		return rows

	def get_columns(self):
		columns = [
			{
				"label": _("Payment Date"),
				"fieldname": "payment_date",
				"fieldtype": "Date",
				"width": 80,
			},
			{
				"label": _("Payment Document"),
				"fieldname": "voucher_no",
				"fieldtype": "Dynamic Link",
				"options": "voucher_type",
				"width": 130,
			},
			{
				"label": _("Invoice Date"),
				"fieldname": "invoice_date",
				"fieldtype": "Date",
				"width": 80,
			},
			{
				"label": _("Invoice Document"),
				"fieldname": "against_voucher",
				"fieldtype": "Dynamic Link",
				"options": "against_voucher_type",
				"width": 130,
			},
			{
				"label": _("Bill No"),
				"fieldname": "bill_no",
				"fieldtype": "Data",
				"width": 80,
			},
			{
				"label": _("Bill Date"),
				"fieldname": "bill_date",
				"fieldtype": "Date",
				"width": 80,
			},
			{
				"label": _("Due Date"),
				"fieldname": "due_date",
				"fieldtype": "Date",
				"width": 80,
			},
			{
				"label": _(self.filters.party_type),
				"fieldname": "party",
				"fieldtype": "Link",
				"options": self.filters.party_type,
				"width": 80 if self.show_party_name else 150,
			},
			{
				"label": _(self.filters.party_type) + " Name",
				"fieldname": "party_name",
				"fieldtype": "Data",
				"width": 150
			},
			{
				"label": _("Payment Amount"),
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"fieldname": "payment_amount",
				"width": 110,
			},
			{
				"label": _("Contribution Amount"),
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"fieldname": "allocated_payment_amount",
				"width": 110,
			},
			{
				"label": _("Contribution"),
				"fieldtype": "Percent",
				"fieldname": "allocated_percentage",
				"width": 90,
			},
			{
				"label": _("Age"),
				"fieldtype": "Int",
				"fieldname": "age",
				"width": 45,
			},
			{
				"label": _("Sales Person"),
				"fieldtype": "Data",
				"fieldname": "sales_person",
				"width": 150,
			},
			{
				"label": _("Account Manager"),
				"fieldtype": "Link",
				"fieldname": "account_manager",
				"options": "Sales Person",
				"width": 120,
			},
			{
				"fieldname": "territory",
				"label": _("Territory"),
				"fieldtype": "Link",
				"options": "Territory",
				"width": 100
			},
		]

		self.ageing_columns = self.get_ageing_columns()
		columns += self.ageing_columns

		columns += [
			{
				"label": _("Payment Remarks"),
				"fieldtype": "Data",
				"fieldname": "payment_remarks",
				"width": 150,
			},
			{
				"label": _("Invoice Remarks"),
				"fieldtype": "Data",
				"fieldname": "invoice_remarks",
				"width": 150,
			},
			{
				"label": _("Cost Center"),
				"fieldtype": "Link",
				"fieldname": "cost_center",
				"options": "Cost Center",
				"width": 80,
			},
			{
				"label": _("Branch"),
				"fieldtype": "Link",
				"options": "Branch",
				"fieldname": "branch",
				"width": 80
			},
			{
				"label": _("Project"),
				"fieldtype": "Link",
				"fieldname": "project",
				"options": "Project",
				"width": 85,
			},
			{
				"fieldname": "customer_group",
				"label": _("Customer Group"),
				"fieldtype": "Link",
				"options": "Customer Group",
				"width": 100
			},
			{
				"fieldname": "supplier_group",
				"label": _("Supplier Group"),
				"fieldtype": "Link",
				"options": "Supplier Group",
				"width": 100
			},
		]

		if not self.show_party_name:
			columns = [c for c in columns if c.get("fieldname") != "party_name"]

		if self.filters.party_type != "Customer":
			columns = [c for c in columns if c.get("fieldname") not in (
				"customer_group", "sales_person", "account_manager", "territory",
			)]

		if self.filters.party_type != "Supplier":
			columns = [c for c in columns if c.get("fieldname") not in (
				"supplier_group", "bill_no", "bill_date",
			)]

		if not self.filters.sales_person:
			columns = [c for c in columns if c.get("fieldname") not in (
				"allocated_payment_amount", "allocated_percentage",
			)]

		if not self.has_cost_center:
			columns = [c for c in columns if c.get("fieldname") != "cost_center"]

		if not self.has_branch:
			columns = [c for c in columns if c.get("fieldname") != "branch"]

		if not self.has_project:
			columns = [c for c in columns if c.get("fieldname") != "project"]

		if not self.has_account_manager:
			columns = [c for c in columns if c.get("fieldname") != "account_manager"]

		return columns

	def get_ageing_columns(self):
		ageing_columns = []
		lower_limit = 0
		for i, upper_limit in enumerate(self.ageing_range):
			ageing_columns.append({
				"label": "{0}-{1}".format(lower_limit, upper_limit),
				"fieldname": "range{}".format(i+1),
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"ageing_column": 1,
				"width": 100
			})
			lower_limit = upper_limit + 1

		ageing_columns.append({
			"label": "{0}-Above".format(lower_limit),
			"fieldname": "range{}".format(self.ageing_column_count),
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"ageing_column": 1,
			"width": 100
		})
		return ageing_columns
