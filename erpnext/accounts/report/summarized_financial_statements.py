import frappe
from frappe import _
from frappe.utils import flt, cint, cstr, getdate, get_first_day, get_year_start, add_years, get_year_ending
from erpnext import get_default_company
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children
)
from erpnext.accounts.report.financial_statements import get_cost_centers_with_children


class SummarizedFinancialReport:
	total_fields = []
	total_with_display_fields = []

	def __init__(self, filters=None):
		self._account_group_docs = {}
		self.filters = frappe._dict(filters or {})

	def validate_filters(self):
		if not self.filters.company:
			self.filters.company = get_default_company()
		if not self.filters.company:
			frappe.throw(_("Company is mandatory"))

		self.filters.report_date = getdate(self.filters.report_date)
		self.filters.month_start_date = get_first_day(self.filters.report_date)
		self.filters.year_start_date = get_year_start(self.filters.report_date)
		self.filters.year_end_date = get_year_ending(self.filters.report_date)

		self.filters.prev_year_date = add_years(self.filters.report_date, -1)
		self.filters.prev_year_month_start = add_years(self.filters.month_start_date, -1)
		self.filters.prev_year_start = add_years(self.filters.year_start_date, -1)
		self.filters.prev_year_end = add_years(self.filters.year_end_date, -1)

	def get_data(self):
		report_type = self.get_report_type()

		current_account_group = self.filters.get('account_group')
		is_root = False
		if not current_account_group:
			is_root = True
			current_account_group = frappe.db.get_value(
				"Account Group",
				{
					"company": self.filters.get('company'),
					"is_root_level": 1,
					"report_type": report_type,
				},
				"name",
			)

			if not current_account_group:
				frappe.throw(_("Please configure Root Level {0} Group or filter by Account Group").format(report_type))

		data = self.get_account_group_data(current_account_group)

		if not is_root:
			totals = {k: 0 for k in self.total_with_display_fields}
			for row in data:
				if row.get('row_type') in ['Account', 'Account Group']:
					for key in totals:
						totals[key] += flt(row.get(key))

			data.append(frappe._dict({
				'row_type': 'Total',
				'account_display': 'Total',
				'is_bold': 1,
				**totals
			}))

		return data

	def get_gl_data(self, accounts, to_date, from_date=None, aggregate=False):
		if not accounts:
			return []

		dimension_conditions, dimension_args = self.get_dimension_conditions()

		args = {
			"company": self.filters.company,
			"accounts": accounts,
			"to_date": to_date,
			"from_date": from_date,
			**dimension_args,
		}
		if from_date:
			date_condition = "and posting_date between %(from_date)s and %(to_date)s"
		else:
			date_condition = "and posting_date <= %(to_date)s"

		fields = ["account"]

		group_by = ""
		order_by = ""

		if aggregate:
			fields += [
				"sum(debit) as debit",
				"sum(credit) as credit",
			]
			group_by = "GROUP BY account"
		else:
			fields += [
				"debit",
				"credit",
				"posting_date",
			]
			order_by = "ORDER BY posting_date"

		fields_str = ", ".join(fields)

		return frappe.db.sql(f"""
			SELECT {fields_str}
			FROM `tabGL Entry`
			WHERE
				company = %(company)s
				and account in %(accounts)s
				{date_condition}
				{dimension_conditions}
			{group_by}
			{order_by}
		""", args, as_dict=1)

	def get_dimension_conditions(self):
		dimension_conditions = []
		args = {}

		if self.filters.get("cost_center"):
			args["cost_center"] = get_cost_centers_with_children(self.filters.cost_center)
			dimension_conditions.append("cost_center in %(cost_center)s")

		accounting_dimensions = get_accounting_dimensions(as_list=False)

		for dimension in accounting_dimensions:
			if self.filters.get(dimension.fieldname):
				if frappe.get_cached_value('DocType', dimension.document_type, 'is_tree'):
					args[dimension.fieldname] = get_dimension_with_children(dimension.document_type, self.filters.get(dimension.fieldname))
					dimension_conditions.append("{0} in %({0})s".format(dimension.fieldname))
				else:
					args[dimension.fieldname] = self.filters.get(dimension.fieldname)
					dimension_conditions.append("{0} = %({0})s".format(dimension.fieldname))

		dimension_conditions = " AND " + " AND ".join(dimension_conditions) if dimension_conditions else ""

		return dimension_conditions, args

	def get_account_group_data(self, group_name):
		"""Aggregate account and group data for a given group."""
		data = []
		group = self.get_account_group_doc(group_name)
		group_root_type = group.root_type

		group_account_map = self.get_accounts_in_account_group(group)
		all_accounts = group_account_map.get(group.name, [])
		account_totals = self.get_account_totals(all_accounts)

		# Calculate Child Group Totals
		child_group_totals = {}
		for row in group.rows:
			if row.row_type != "Account Group":
				continue

			child_group_doc = self.get_account_group_doc(row.account_group)

			group_accounts = group_account_map.get(row.account_group) or set()
			group_totals = self.get_group_totals(group_accounts, account_totals)
			group_totals["root_type"] = child_group_doc.root_type

			child_group_totals[row.account_group] = group_totals

		running_grand_totals = {f: 0 for f in self.total_fields}
		running_section_totals = {f: 0 for f in self.total_fields}
		previous_section_totals = {}

		for row in group.rows:
			if row.row_type == "Account":
				totals = account_totals.get(row.account) or {}
				data.append(self.get_row(
					row.row_type,
					row_value=row.account,
					row_label=row.section_name,
					totals=totals,
					group_root_type=group_root_type,
					reverse_sign=row.reverse_sign,
				))

				for f in self.total_fields:
					running_grand_totals[f] += flt(totals.get(f))
					running_section_totals[f] += flt(totals.get(f))

			elif row.row_type == "Account Group":
				totals = child_group_totals.get(row.account_group) or {}
				data.append(self.get_row(
					row.row_type,
					row_value=row.account_group,
					row_label=row.section_name,
					totals=totals,
					group_root_type=group_root_type,
					reverse_sign=row.reverse_sign,
				))

				for f in self.total_fields:
					running_grand_totals[f] += flt(totals.get(f))
					running_section_totals[f] += flt(totals.get(f))

			elif row.row_type == "Section Break":
				data.append(self.get_row(
					row.row_type,
					row_value=row.section_name,
					row_label=row.section_name,
					is_bold=True,
					group_root_type=group_root_type,
				))

			elif row.row_type == "Section Total":
				section_totals = self.calculate_section_totals(
					row,
					child_group_totals,
					account_totals,
					previous_section_totals,
					running_grand_totals,
					running_section_totals,
				)

				data.append(self.get_row(
					row.row_type,
					row_value=row.section_name,
					row_label=row.section_name,
					totals=section_totals,
					is_bold=True,
					group_root_type=group_root_type,
					reverse_sign=row.reverse_sign,
				))

				previous_section_totals[row.section_name] = section_totals
				running_section_totals = {f: 0 for f in self.total_fields}

			elif row.row_type == "Profit and Loss":
				net_profit_loss = self.get_net_profit_loss()
				data.append(self.get_row(
					row.row_type,
					row_value=row.section_name,
					row_label=row.section_name,
					totals=net_profit_loss,
					is_bold=True,
					group_root_type=group_root_type,
					reverse_sign=row.reverse_sign,
				))

		return data

	def get_accounts_in_account_group(self, account_group):
		account_map = {}

		self.get_accounts_in_child_account_group(account_group.name, account_group.name, account_map)
		for row in account_group.rows:
			if row.row_type == "Account Group":
				self.get_accounts_in_child_account_group(row.account_group, row.account_group, account_map)

		return account_map

	def get_accounts_in_child_account_group(self, current_group_name, root_group_name, account_map):
		current_group = self.get_account_group_doc(current_group_name)

		for row in current_group.rows:
			if row.row_type == "Account":
				account_map.setdefault(root_group_name, set()).add(row.account)
			elif row.row_type == "Account Group":
				self.get_accounts_in_child_account_group(row.account_group, root_group_name, account_map)

	def get_account_totals(self, all_accounts):
		raise NotImplementedError("get_account_totals not implemented")

	def get_group_totals(self, group_accounts, account_totals):
		group_totals = frappe._dict({f: 0 for f in self.total_fields})

		for account in group_accounts:
			totals = account_totals.get(account)
			if not totals:
				continue

			for f in self.total_fields:
				group_totals[f] += flt(totals.get(f))

		return group_totals

	def calculate_section_totals(
		self,
		row,
		child_child_groups,
		account_totals,
		previous_section_totals,
		running_grand_totals,
		running_section_totals,
	):
		options = cstr(row.options).strip()
		if not options or options == "Running Total":
			return running_grand_totals.copy()
		elif options == "Section Total":
			return running_section_totals.copy()

		included_totals = []
		included_categories = set()

		for line in options.split('\n'):
			group_code = line.strip()
			if not group_code:
				continue

			totals_obj = None
			if group_code in child_child_groups:
				totals_obj = child_child_groups[group_code]
			elif group_code in account_totals:
				totals_obj = account_totals[group_code]
			elif group_code in previous_section_totals:
				totals_obj = previous_section_totals[group_code]
			elif group_code in ("Section Total", "_Section Total_"):
				totals_obj = running_section_totals
			elif group_code in ("Running Total", "_Running Total_"):
				totals_obj = running_grand_totals

			if totals_obj:
				included_totals.append(totals_obj)
				if totals_obj.get("root_type"):
					included_categories.add(totals_obj["root_type"])
			else:
				frappe.msgprint(_("Invalid Section Total reference to {0} in Section {1}").format(
					frappe.bold(group_code), frappe.bold(row.section_name)
				), indicator="orange")

		section_totals = {key: 0 for key in self.total_fields}

		for totals_obj in included_totals:
			for key in section_totals:
				section_totals[key] += flt(totals_obj.get(key))

		if len(included_categories) == 1:
			section_totals["root_type"] = list(included_categories)[0]

		return section_totals

	def get_net_profit_loss(self):
		return {f: 0 for f in self.total_fields}

	def get_row(
		self,
		row_type,
		row_value,
		row_label,
		totals=None,
		is_bold=False,
		group_root_type=None,
		reverse_sign=False,
	):
		row = frappe._dict()

		no_values = True
		if totals is not None:
			no_values = False

		if not no_values:
			for f in self.total_fields:
				row[f] = 0

		if not totals:
			totals = frappe._dict()

		row.update(totals)

		row["row_type"] = row_type
		row["account_display"] = row_label or row_value or ""
		row["root_type"] = totals.get("root_type") or group_root_type
		row["is_bold"] = cint(is_bold)

		if row_type == "Account":
			row["account_display"] = row_label or row_value or ""
			row["account"] = row_value
			row["link_type"] = "Account"
		elif row_type == "Account Group":
			row["account_group"] = row_value
			row["link_type"] = "Account Group"

		if not no_values:
			multiplier = self.get_display_value_multiplier(row)
			if reverse_sign:
				multiplier = multiplier * -1

			for f in self.total_fields:
				row[f"{f}_display"] = row[f] * multiplier

		return row

	def get_display_value_multiplier(self, row):
		return 1

	def get_account_group_doc(self, group_name):
		if not self._account_group_docs.get(group_name):
			self._account_group_docs[group_name] = frappe.get_doc("Account Group", group_name)

		return self._account_group_docs[group_name]

	@staticmethod
	def get_report_type():
		raise NotImplementedError("get_report_type not implemented")
