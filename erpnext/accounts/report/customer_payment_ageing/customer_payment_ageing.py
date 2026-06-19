# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import erpnext
from frappe import _, scrub
from frappe.utils import getdate, flt, cint, cstr
from erpnext.accounts.utils import get_currency_precision
from erpnext.accounts.report.financial_statements import get_cost_centers_with_children
from erpnext.accounts.report.accounts_receivable.accounts_receivable import get_ageing_data
from erpnext.accounts.report.customer_ledger_summary.customer_ledger_summary import get_adjustment_details
from frappe.desk.query_report import group_report_data


def execute(filters=None):
	return PaymentAgeingReport("Customer", filters).run()


class PaymentAgeingReport:
	def __init__(self, party_type, filters=None):
		self.filters = frappe._dict(filters or {})
		self.filters.party_type = party_type
		self.filters.party = self.filters.get(scrub(self.filters.get("party_type")))

		self.adjustment_details = frappe._dict()

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
		self.get_adjustment_data()

		rows = self.prepare_rows()
		columns = self.get_columns()

		grouped_data = self.get_grouped_data(columns, rows)
		chart = None  # self.get_chart_data(data) # Todo chart?

		return columns, grouped_data, None, chart

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
			"gle.remarks as payment_remarks",
			"gle.against_voucher_type",
			"gle.against_voucher",
			"gle.company",
			"gle.account",
			"gle.cost_center",
			"gle.project",
			"gle.account_currency",
			"100 as allocated_percentage",
		]

		if self.use_account_currency():
			select_fields += [
				"sum(gle.debit_in_account_currency) as debit",
				"sum(gle.credit_in_account_currency) as credit",
			]
		else:
			select_fields += [
				"sum(gle.debit) as debit",
				"sum(gle.credit) as credit",
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
				"cus.territory as customer_territory",
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
			group by gle.voucher_type, gle.voucher_no, gle.party, ifnull(gle.against_voucher_type, ''), ifnull(gle.against_voucher, '')
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

	def get_adjustment_data(self):
		if self.filters.account_currency != self.filters.company_currency:
			return

		self.voucher_nos = set()
		for d in self.payment_gles:
			self.voucher_nos.add((d.voucher_type, d.voucher_no))

		gl_entries = []
		if self.voucher_nos:
			gl_entries = frappe.db.sql("""
				select
					posting_date, account, party, voucher_type, voucher_no, against_voucher_type, against_voucher,
					debit, credit, debit_in_account_currency, credit_in_account_currency
				from
					`tabGL Entry`
				where voucher_type not in ('Sales Invoice', 'Purchase Invoice')
					and (voucher_type, voucher_no) in %(voucher_nos)s
					and (voucher_type, voucher_no) in (
						select voucher_type, voucher_no from `tabGL Entry` gle, `tabAccount` acc
						where acc.name = gle.account and (acc.root_type in ('Income', 'Expense') or acc.account_type = 'Tax')
					)
			""", {"voucher_nos": self.voucher_nos}, as_dict=True)

		adjustment_voucher_entries = {}
		for gle in gl_entries:
			adjustment_voucher_entries.setdefault((gle.voucher_type, gle.voucher_no), [])
			adjustment_voucher_entries[(gle.voucher_type, gle.voucher_no)].append(gle)

		self.adjustment_details = get_adjustment_details(adjustment_voucher_entries, self.reverse_dr_or_cr, self.dr_or_cr)

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

			if voucher_details:
				for k, v in voucher_details.items():
					if v or isinstance(v, (int, float)):
						row[k] = v

			# Remarks
			row.invoice_remarks = row.invoice_user_remark or row.invoice_remarks

			# Currency
			row["currency"] = gle.account_currency if self.use_account_currency() else self.company_currency
			self.account_currency = row["currency"]

			# Payment Deductions
			voucher_tuple = (gle.voucher_type, gle.voucher_no)
			against_voucher_tuple = (cstr(gle.against_voucher_type), cstr(gle.against_voucher))
			adjustments_obj = (
				self.adjustment_details.detailed
				.get(voucher_tuple, {})
				.get(gle.party, {})
				.get(against_voucher_tuple, {})
			)

			total_adjustment = sum([amount for amount in adjustments_obj.values()])
			row.payment_amount -= total_adjustment
			row.total_deductions = total_adjustment

			for account in self.adjustment_details.accounts:
				row["adj_" + scrub(account)] = adjustments_obj.get(account, 0)

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

	def use_account_currency(self):
		return self.filters.get("party") or self.filters.get("account")

	def get_grouped_data(self, columns, data):
		level1 = self.filters.get("group_by", "").replace("Group by ", "")
		level2 = self.filters.get("group_by_2", "").replace("Group by ", "")
		level1_fieldname = "party" if level1 in ['Customer', 'Supplier'] else scrub(level1)
		level2_fieldname = "party" if level2 in ['Customer', 'Supplier'] else scrub(level2)

		group_by = [None]
		group_by_labels = {}
		if level1:
			group_by.append(level1_fieldname)
			group_by_labels[level1_fieldname] = level1
		if level2:
			group_by.append(level2_fieldname)
			group_by_labels[level2_fieldname] = level2

		if len(group_by) <= 1:
			return data

		total_fields = [c['fieldname'] for c in columns
			if c['fieldtype'] in ['Float', 'Currency', 'Int'] and c['fieldname'] != 'age']

		def postprocess_group(group_object, grouped_by):
			# Copy grouped by into total row
			for f, g in grouped_by.items():
				group_object.totals[f] = g

			if not group_object.group_field:
				group_object.totals['voucher_no'] = "'Total'"
			else:
				group_object.totals['voucher_no'] = "'{0}: {1}'".format(_(group_object.group_label), group_object.group_value or "None")

			if group_object.group_field == 'party':
				group_object.totals['party'] = group_object.group_value
				group_object.totals['party_name'] = group_object.rows[0].get('party_name')
				group_object.totals['currency'] = group_object.rows[0].get("currency")
				group_object.totals['account_manager'] = group_object.rows[0].get("account_manager")
				group_object.totals["customer_group"] = group_object.rows[0].get("customer_group")
				group_object.totals["territory"] = group_object.rows[0].get("customer_territory")

		return group_report_data(
			data,
			group_by,
			total_fields=total_fields,
			postprocess_group=postprocess_group,
			group_by_labels=group_by_labels,
		)

	def get_columns(self):
		has_grouping = self.filters.get("group_by") or self.filters.get("group_by_2")

		columns = [
			{
				"label": _("Payment Document"),
				"fieldname": "voucher_no",
				"fieldtype": "Dynamic Link",
				"options": "voucher_type",
				"width": 130 if not has_grouping else 300,
			},
			{
				"label": _("Payment Date"),
				"fieldname": "payment_date",
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
				"label": _("Invoice Date"),
				"fieldname": "invoice_date",
				"fieldtype": "Date",
				"width": 80,
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
				"options": "currency",
				"fieldname": "payment_amount",
				"width": 110,
			},
			{
				"label": _("Total Deduction"),
				"fieldname": "total_deductions",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 110,
			},
		]

		if self.filters.show_deduction_details:
			for account in self.adjustment_details.accounts:
				columns.append({
					"label": account,
					"fieldname": "adj_" + scrub(account),
					"fieldtype": "Currency",
					"options": "currency",
					"width": 110,
					"is_adjustment": 1
				})

		columns += [
			{
				"label": _("Contribution Amount"),
				"fieldtype": "Currency",
				"options": "currency",
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
				"options": "currency",
				"ageing_column": 1,
				"width": 100
			})
			lower_limit = upper_limit + 1

		ageing_columns.append({
			"label": "{0}-Above".format(lower_limit),
			"fieldname": "range{}".format(self.ageing_column_count),
			"fieldtype": "Currency",
			"options": "currency",
			"ageing_column": 1,
			"width": 100
		})
		return ageing_columns
