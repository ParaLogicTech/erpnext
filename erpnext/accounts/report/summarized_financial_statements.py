import frappe
from frappe import _
from frappe.utils import flt, cint, getdate, get_first_day, get_year_start, add_years
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

		self.filters.prev_year_date = add_years(self.filters.report_date, -1)
		self.filters.prev_year_month_start = add_years(self.filters.month_start_date, -1)
		self.filters.prev_year_start = add_years(self.filters.year_start_date, -1)

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
				'account_name': 'Total',
				'is_bold': 1,
				**totals
			}))

		return data

	def get_gl_data(self, accounts, to_date, from_date=None, aggregate=False):
		if not accounts:
			return []

		if isinstance(accounts, set):
			accounts = list(accounts)

		dimension_conditions, dimension_args = self.get_dimension_conditions()

		args = {
			"company": self.filters.company,
			"to_date": to_date,
			"from_date": from_date,
			**dimension_args,
		}
		date_condition = (
			"AND posting_date BETWEEN %(from_date)s AND %(to_date)s"
			if from_date else
			"AND posting_date <= %(to_date)s"
		)

		fields = ["account"]
		if aggregate:
			fields += ["SUM(debit) as debit", "SUM(credit) as credit"]
			order_by = ""
		else:
			fields += ["debit", "credit", "posting_date"]
			order_by = "ORDER BY posting_date"

		def run_gl_query(group_by_fields, extra_fields, account_condition, args):
			group_by_clause = "GROUP BY " + ", ".join(group_by_fields) if aggregate else ""
			fields_str = ", ".join(fields + extra_fields)
			query = f"""
	            SELECT {fields_str}
	            FROM `tabGL Entry`
	            WHERE
	                company = %(company)s
	                {date_condition}
	                {dimension_conditions}
	                {account_condition}
	            {group_by_clause}
	            {order_by}
	        """
			return frappe.db.sql(query, args, as_dict=True)

		leaf_accounts = set()
		leaf_accounts_with_pt = []
		leaf_accounts_with_pt_and_party = []

		for acc, pt, party in accounts:
			if pt is None and party is None:
				leaf_accounts.add(acc)
			elif pt is not None and party is None:
				leaf_accounts_with_pt.append((acc, pt))
			elif pt is not None and party is not None:
				leaf_accounts_with_pt_and_party.append((acc, pt, party))

		results = []

		# No filters
		if leaf_accounts:
			args = args.copy()
			account_placeholders = ", ".join([f"%(ua_{i})s" for i in range(len(leaf_accounts))])
			for i, acc in enumerate(leaf_accounts):
				args[f"ua_{i}"] = acc
			account_condition = f"AND account IN ({account_placeholders})"

			leaf_results = run_gl_query(
				group_by_fields=["account"],
				extra_fields=[],
				account_condition=account_condition,
				args=args,
			)
			for row in leaf_results:
				row["account"] = (row["account"], None, None)
			results.extend(leaf_results)

		# Only party_type
		if leaf_accounts_with_pt:
			or_conditions, or_args = [], {}
			for i, (acc, pt) in enumerate(leaf_accounts_with_pt):
				or_conditions.append(f"(account = %(f_acc_{i})s AND party_type = %(f_pt_{i})s)")
				or_args[f"f_acc_{i}"] = acc
				or_args[f"f_pt_{i}"] = pt
			account_condition = f"AND ({' OR '.join(or_conditions)})"
			args = {**args, **or_args}

			pt_results = run_gl_query(
				group_by_fields=["account", "party_type"],
				extra_fields=["party_type"],
				account_condition=account_condition,
				args=args,
			)
			for row in pt_results:
				row["account"] = (row["account"], row.get("party_type"), None)
			results.extend(pt_results)

		# party_type + party
		if leaf_accounts_with_pt_and_party:
			or_conditions, or_args = [], {}
			for i, (acc, pt, party) in enumerate(leaf_accounts_with_pt_and_party):
				or_conditions.append(
					f"(account = %(f_acc_{i})s AND party_type = %(f_pt_{i})s AND party = %(f_party_{i})s)"
				)
				or_args[f"f_acc_{i}"] = acc
				or_args[f"f_pt_{i}"] = pt
				or_args[f"f_party_{i}"] = party
			account_condition = f"AND ({' OR '.join(or_conditions)})"
			args = {**args, **or_args}

			pt_party_results = run_gl_query(
				group_by_fields=["account", "party_type", "party"],
				extra_fields=["party_type", "party"],
				account_condition=account_condition,
				args=args,
			)
			for row in pt_party_results:
				row["account"] = (row["account"], row.get("party_type"), row.get("party"))
			results.extend(pt_party_results)

		return results

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

		running_totals = {f: 0 for f in self.total_fields}
		for row in group.rows:
			if row.row_type == "Account":
				totals = account_totals.get((row.account, row.party_type or None, row.party or None)) or {}
				data.append(self.get_row(
					row.row_type,
					row.account,
					totals=totals,
					group_root_type=group_root_type,
					reverse_sign=row.reverse_sign,
					party_type = row.party_type,
					party = row.party
				))

				for f in self.total_fields:
					running_totals[f] += flt(totals.get(f))

			elif row.row_type == "Account Group":
				totals = child_group_totals.get(row.account_group) or {}
				data.append(self.get_row(
					row.row_type,
					row.account_group,
					totals=totals,
					group_root_type=group_root_type,
					reverse_sign=row.reverse_sign,
				))

				for f in self.total_fields:
					running_totals[f] += flt(totals.get(f))

			elif row.row_type == "Section Break":
				data.append(self.get_row(
					row.row_type,
					row.section_name,
					is_bold=True,
					group_root_type=group_root_type,
				))

			elif row.row_type == "Section Group":
				section_totals = self.calculate_section_totals(row, child_group_totals, running_totals)
				data.append(self.get_row(
					row.row_type,
					row.section_name,
					totals=section_totals,
					is_bold=True,
					group_root_type=group_root_type,
					reverse_sign=row.reverse_sign,
				))

			elif row.row_type == "Profit and Loss":
				net_profit_loss = self.get_net_profit_loss()
				data.append(self.get_row(
					row.row_type,
					row.section_name,
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
				account_key = (row.account, row.party_type or None, row.party or None)
				account_map.setdefault(root_group_name, set()).add(account_key)
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

	def calculate_section_totals(self, row, child_groups, running_totals):
		if not row.section_account_groups:
			return running_totals.copy()

		included_groups = []
		included_categories = set()

		for line in row.section_account_groups.split('\n'):
			group_code = line.strip()
			if group_code and group_code in child_groups:
				group_info = child_groups[group_code]
				included_groups.append(group_info)
				included_categories.add(group_info["root_type"])

		section_totals = {key: 0 for key in self.total_fields}
		for group_info in included_groups:
			for key in section_totals:
				section_totals[key] += flt(group_info.get(key))

		if len(included_categories) == 1:
			section_totals["root_type"] = list(included_categories)[0]

		return section_totals

	def get_net_profit_loss(self):
		return {f: 0 for f in self.total_fields}

	def get_row(self, row_type, row_value, totals=None, is_bold=False, group_root_type=None, reverse_sign=False, party_type=None, party=None):
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
		row["account_name"] = row_value or ""
		row["root_type"] = totals.get("root_type") or group_root_type
		row["is_bold"] = cint(is_bold)

		if row_type == "Account":
			row["account"] = row_value
			row["link_type"] = "Account"
			row["party_type"] = party_type
			row['party'] = party
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
