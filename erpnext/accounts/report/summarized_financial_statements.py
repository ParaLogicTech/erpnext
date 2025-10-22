import frappe
import erpnext
from frappe import _
from frappe.utils import flt, cint, cstr, getdate, get_first_day, get_year_start, add_years, get_year_ending
from erpnext import get_default_company
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children
)
from erpnext.accounts.report.financial_statements import get_cost_centers_with_children


class SummarizedFinancialReport:
	def __init__(self, filters=None):
		self._account_group_docs = {}
		self._get_account_group_balance = {}
		self._get_asset_additions_and_disposals = {}
		self._asset_disposal_jvs = None

		self.filters = frappe._dict(filters or {})

		self.filters.report_date = getdate(self.filters.report_date)
		self.filters.month_start_date = get_first_day(self.filters.report_date)
		self.filters.year_start_date = get_year_start(self.filters.report_date)
		self.filters.year_end_date = get_year_ending(self.filters.report_date)

		self.filters.prev_year_date = add_years(self.filters.report_date, -1)
		self.filters.prev_year_month_start = add_years(self.filters.month_start_date, -1)
		self.filters.prev_year_start = add_years(self.filters.year_start_date, -1)
		self.filters.prev_year_end = add_years(self.filters.year_end_date, -1)

		self.value_fields = {}
		self.setup_fields()
		self.value_fieldnames = list(self.value_fields.keys())
		self.value_and_display_fieldnames = self.value_fieldnames + [f"{f}_display" for f in self.value_fieldnames]

	def setup_fields(self):
		pass

	def validate_filters(self):
		if not self.filters.company:
			self.filters.company = get_default_company()
		if not self.filters.company:
			frappe.throw(_("Company is mandatory"))

	def get_data(self):
		self.current_account_group = self.filters.get('account_group')
		is_root = False
		if not self.current_account_group:
			is_root = True
			self.current_account_group = self.get_root_account_group()
			if not self.current_account_group:
				frappe.throw(_("Please configure Root Level {0} Group or filter by Account Group").format(
					self.get_report_type()
				))

		data = self.get_account_group_data(self.current_account_group)

		if not is_root:
			totals = {k: 0 for k in self.value_fieldnames}
			for row in data:
				if row.get('row_type') in ['Account', 'Account Group']:
					for f in totals:
						totals[f] += flt(row.get(f))

			for f in self.value_fieldnames:
				totals[f"{f}_display"] = totals[f]

			data.append(frappe._dict({
				'row_type': 'Total',
				'account_display': 'Total',
				'is_bold': 1,
				**totals
			}))

		return data

	def get_root_account_group(self):
		return frappe.db.get_value(
			"Account Group",
			{
				"company": self.filters.get('company'),
				"is_root_level": 1,
				"report_type": self.get_report_type(),
			},
			"name",
		)

	def get_account_group_data(self, group_name):
		"""Aggregate account and group data for a given group."""
		data = []
		group = self.get_account_group_doc(group_name)
		group_root_type = group.root_type

		self.group_account_map = self.get_accounts_in_account_group(group)
		all_accounts = self.group_account_map.get(group.name, [])
		self.account_totals = self.get_account_totals(all_accounts)
		self.child_group_totals = self.get_child_group_totals(group, self.group_account_map)

		self.account_totals_by_field = {}
		self.group_totals_by_field = {}
		for f in self.value_fieldnames:
			self.account_totals_by_field[f] = {}
			self.group_totals_by_field[f] = {}
			for key, tot in self.account_totals.items():
				self.account_totals_by_field[f][key] = flt(tot.get(f))
			for key, tot in self.child_group_totals.items():
				self.group_totals_by_field[f][key] = flt(tot.get(f))

		self.variable_values = self.evaluate_variable_values(group)
		self.variable_values_by_field = {}
		for f in self.value_fieldnames:
			self.variable_values_by_field[f] = frappe._dict()
			for key, tot in self.variable_values.items():
				self.variable_values_by_field[f][key] = tot.get(f)

		running_grand_totals = {f: 0 for f in self.value_fieldnames}
		running_section_totals = {f: 0 for f in self.value_fieldnames}
		previous_section_totals = {}

		for row in group.rows:
			if row.row_type == "Account":
				if row.hidden and not self.filters.show_hidden:
					continue

				totals = self.account_totals.get(row.account) or {}
				data.append(self.get_row(
					row,
					totals=totals,
					group_root_type=group_root_type,
				))

				for f in self.value_fieldnames:
					running_grand_totals[f] += flt(totals.get(f))
					running_section_totals[f] += flt(totals.get(f))

			elif row.row_type == "Account Group":
				if row.hidden and not self.filters.show_hidden:
					continue

				totals = self.child_group_totals.get(row.account_group) or {}
				data.append(self.get_row(
					row,
					totals=totals,
					group_root_type=group_root_type,
				))

				for f in self.value_fieldnames:
					running_grand_totals[f] += flt(totals.get(f))
					running_section_totals[f] += flt(totals.get(f))

			elif row.row_type == "Formula":
				formula_values = self.evaluate_formula_values(
					row,
					previous_section_totals,
					running_grand_totals,
					running_section_totals,
				)
				previous_section_totals[row.section_name] = formula_values

				if not row.hidden:
					if row.value_type == "Currency" or not row.value_type:
						for f in self.value_fieldnames:
							running_grand_totals[f] += flt(formula_values.get(f))
							running_section_totals[f] += flt(formula_values.get(f))

				if not row.hidden or self.filters.show_hidden:
					data.append(self.get_row(
						row,
						totals=formula_values,
						group_root_type=group_root_type,
					))

			elif row.row_type == "Section Break":
				if row.hidden and not self.filters.show_hidden:
					continue

				data.append(self.get_row(
					row,
					is_bold=True,
					group_root_type=group_root_type,
				))

			elif row.row_type == "Section Total":
				section_totals = self.calculate_section_totals(
					row,
					previous_section_totals,
					running_grand_totals,
					running_section_totals,
				)
				previous_section_totals[row.section_name] = section_totals

				if not row.hidden:
					running_section_totals = {f: 0 for f in self.value_fieldnames}

				if not row.hidden or self.filters.show_hidden:
					data.append(self.get_row(
						row,
						totals=section_totals,
						is_bold=True,
						group_root_type=group_root_type,
					))

			elif row.row_type == "Profit and Loss":
				if row.hidden and not self.filters.show_hidden:
					continue

				net_profit_loss = self.get_net_profit_loss()
				data.append(self.get_row(
					row,
					totals=net_profit_loss,
					is_bold=True,
					group_root_type=group_root_type,
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

	def get_account_details(self, all_accounts):
		if not all_accounts:
			return {}

		accounts_data = frappe.db.sql("""
			select name, account_type, report_type
			from `tabAccount`
			where name in %s
		""", [all_accounts], as_dict=1)

		account_details = {}
		for d in accounts_data:
			account_details[d.name] = d

		return account_details

	def get_account_totals(self, all_accounts):
		raise NotImplementedError("get_account_totals not implemented")

	def _get_account_totals(self, all_accounts, gl_fields, dr_or_cr):
		template = frappe._dict({f: 0 for f in self.value_fieldnames})

		account_totals = {}
		for fieldname, field_info in gl_fields.items():
			gl_data = self.get_gl_data(
				all_accounts,
				from_date=field_info.from_date,
				to_date=field_info.to_date,
				aggregate=True,
			)

			for d in gl_data:
				group = account_totals.setdefault(d.account, template.copy())
				if dr_or_cr == "credit":
					group[fieldname] += d.credit - d.debit
				else:
					group[fieldname] += d.debit - d.credit

		return account_totals

	def get_child_group_totals(self, group_doc, group_account_map):
		child_group_totals = {}
		for row in group_doc.rows:
			if row.row_type != "Account Group":
				continue

			child_group_doc = self.get_account_group_doc(row.account_group)

			group_accounts = group_account_map.get(row.account_group) or set()
			group_totals = self.get_group_totals(group_accounts)
			group_totals["root_type"] = child_group_doc.root_type

			child_group_totals[row.account_group] = group_totals

		return child_group_totals

	def get_group_totals(self, group_accounts):
		group_totals = frappe._dict({f: 0 for f in self.value_fieldnames})

		for account in group_accounts:
			totals = self.account_totals.get(account)
			if not totals:
				continue

			for f in self.value_fieldnames:
				group_totals[f] += flt(totals.get(f))

		return group_totals

	def evaluate_variable_values(self, group_doc):
		if not group_doc.variables:
			return {}

		from frappe.utils.safe_exec import get_safe_globals
		eval_globals = get_safe_globals()

		variable_values = frappe._dict()
		for d in group_doc.variables:
			values = frappe._dict({f: 0 for f in self.value_fieldnames})

			variable_values_by_field = frappe._dict()
			for f in self.value_fieldnames:
				variable_values_by_field[f] = frappe._dict()
				for key, tot in variable_values.items():
					variable_values_by_field[f][key] = tot.get(f)

			for f, field_info in self.value_fields.items():
				variable_context = frappe._dict({
					"accounts": self.account_totals_by_field[f],
					"account_totals": self.account_totals,

					"groups": self.group_totals_by_field[f],
					"group_totals": self.child_group_totals,

					"variables": variable_values_by_field[f],
					"variable_values": variable_values,

					"fieldname": f,
					"field_info": field_info,
					"filters": self.filters,
				})
				self.extend_eval_context(variable_context)
				variable_context.update(self.get_context_functions())

				try:
					values[f] = frappe.safe_eval(d.expression, eval_globals, eval_locals=variable_context)
				except Exception as e:
					frappe.msgprint(_("Error evaluating variable {0}: {1}".format(
						frappe.bold(d.variable_name), repr(e)
					)), indicator="orange")

			variable_values[d.variable_name] = values

		return variable_values

	def evaluate_formula_values(
		self,
		row,
		previous_section_totals,
		running_grand_totals,
		running_section_totals,
	):
		from frappe.utils.safe_exec import get_safe_globals
		eval_globals = get_safe_globals()

		previous_section_totals_by_field = {}
		for f in self.value_fieldnames:
			previous_section_totals_by_field[f] = {}
			for key, tot in previous_section_totals.items():
				previous_section_totals_by_field[f][key] = flt(tot.get(f))

		formula_values = {}

		for f, field_info in self.value_fields.items():
			formula_context = frappe._dict({
				"accounts": self.account_totals_by_field[f],
				"account_totals": self.account_totals,

				"groups": self.group_totals_by_field[f],
				"group_totals": self.child_group_totals,

				"variables": self.variable_values_by_field[f],
				"variable_values": self.variable_values,

				"previous_sections": previous_section_totals_by_field[f],
				"previous_section_totals": previous_section_totals,

				"running_grand_total": running_grand_totals[f],
				"all_running_grand_totals": running_grand_totals,

				"running_section_total": running_section_totals[f],
				"all_running_section_totals": running_section_totals,

				"fieldname": f,
				"field_info": field_info,
				"filters": self.filters,
			})
			self.extend_eval_context(formula_context)
			formula_context.update(self.get_context_functions())

			try:
				formula_values[f] = frappe.safe_eval(row.options, eval_globals, eval_locals=formula_context)
			except Exception as e:
				frappe.msgprint(_("Error evaluating formula {0} on Row #{1}: {2}".format(
					frappe.bold(row.section_name), row.idx, repr(e)
				)), indicator="orange")

		return formula_values

	def extend_eval_context(self, context):
		frappe.utils.call_hook_method("extend_financial_statement_eval_context", context)

	def get_context_functions(self):
		return {
			"get_account_group_balance": self.get_account_group_balance,
			"get_asset_additions_and_disposals": self.get_asset_additions_and_disposals,
		}

	def get_account_group_balance(self, account_group, to_date):
		if not to_date:
			return 0

		to_date = getdate(to_date)

		def generator():
			account_map = {}
			self.get_accounts_in_child_account_group(account_group, account_group, account_map)
			accounts = account_map.get(account_group, [])

			balance = self.get_gl_data(accounts, to_date=to_date, aggregate=True, group_by_account=False)
			return flt(balance[0].debit) - flt(balance[0].credit) if balance else 0

		key = (account_group, to_date)
		if key not in self._get_account_group_balance:
			self._get_account_group_balance[key] = generator()

		return self._get_account_group_balance[key]

	def get_asset_additions_and_disposals(self, account_group, from_date, to_date):
		template = frappe._dict({"additions": 0, "disposals": 0})
		if not to_date:
			return template

		to_date = getdate(to_date)
		from_date = getdate(from_date) if from_date else None

		def generator():
			out = template.copy()
			account_map = {}
			self.get_accounts_in_child_account_group(account_group, account_group, account_map)
			accounts = account_map.get(account_group, [])
			disposal_jvs = self.get_asset_disposal_jvs()

			gl_data = self.get_gl_data(accounts, from_date=from_date, to_date=to_date, aggregate=False)
			for d in gl_data:
				is_disposal = d.voucher_type == "Sales Invoice" or (d.voucher_type == "Journal Entry" and d.voucher_no in disposal_jvs)

				if is_disposal:
					out["disposals"] += d.credit - d.debit
				else:
					out["additions"] += d.debit - d.credit

			return out

		key = (account_group, from_date, to_date)
		if key not in self._get_asset_additions_and_disposals:
			self._get_asset_additions_and_disposals[key] = generator()

		return self._get_asset_additions_and_disposals[key]

	def get_asset_disposal_jvs(self):
		def generator():
			return set(frappe.db.sql_list("""
				select distinct journal_entry_for_scrap
				from `tabAsset`
				where journal_entry_for_scrap != '' and journal_entry_for_scrap is not null
			"""))

		if self._asset_disposal_jvs is None:
			self._asset_disposal_jvs = generator()

		return self._asset_disposal_jvs

	def calculate_section_totals(
		self,
		row,
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
			if group_code in self.child_group_totals:
				totals_obj = self.child_group_totals[group_code]
			elif group_code in self.account_totals:
				totals_obj = self.account_totals[group_code]
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

		section_totals = {key: 0 for key in self.value_fieldnames}

		for totals_obj in included_totals:
			for key in section_totals:
				section_totals[key] += flt(totals_obj.get(key))

		if len(included_categories) == 1:
			section_totals["root_type"] = list(included_categories)[0]

		return section_totals

	def get_net_profit_loss(self):
		return {f: 0 for f in self.value_fieldnames}

	def get_row(
		self,
		d,
		totals=None,
		is_bold=False,
		group_root_type=None,
	):
		row = frappe._dict()

		no_values = True
		if totals is not None:
			no_values = False

		if not no_values:
			for f in self.value_fieldnames:
				row[f] = 0

		if not totals:
			totals = frappe._dict()

		row.update(totals)

		row["row_type"] = d.row_type
		row["account_display"] = d.section_name or ""
		row["root_type"] = totals.get("root_type") or group_root_type
		row["is_bold"] = cint(d.is_bold or is_bold)
		row["value_type"] = d.value_type or "Currency"
		row["format_precision"] = d.format_precision
		row["currency"] = erpnext.get_company_currency(self.filters.company)
		row["right_align"] = d.right_align

		if d.row_type == "Account":
			row["account"] = d.account
			row["account_display"] = row["account_display"] or d.account
		elif d.row_type == "Account Group":
			row["account_group"] = d.account_group
			row["account_display"] = row["account_display"] or d.account_group

		row["is_fixed_asset_root"] = 0
		if (
			d.row_type == "Account Group"
			and self.get_report_type() == "Balance Sheet"
			and frappe.get_cached_value("Account Group", d.account_group, "is_fixed_asset_root")
		):
			row["is_fixed_asset_root"] = 1

		if not no_values:
			if row.value_type == "Data":
				for f in self.value_fieldnames:
					row[f"{f}_display"] = row[f]
			else:
				multiplier = self.get_display_value_multiplier(row)
				if d.reverse_sign:
					multiplier = multiplier * -1

				for f in self.value_fieldnames:
					row[f"{f}_display"] = row[f] * multiplier if row[f] is not None else None

		return row

	def get_gl_data(self, accounts, to_date, from_date=None, aggregate=False, group_by_account=True):
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

		fields = []
		group_by = ""
		order_by = ""

		if aggregate:
			fields += [
				"sum(debit) as debit",
				"sum(credit) as credit",
			]

			if group_by_account:
				fields.append("account")
				group_by = "GROUP BY account"
		else:
			fields += [
				"account",
				"debit",
				"credit",
				"posting_date",
				"voucher_type",
				"voucher_no",
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

	def get_display_value_multiplier(self, row):
		return 1

	def get_account_group_doc(self, group_name):
		if not self._account_group_docs.get(group_name):
			self._account_group_docs[group_name] = frappe.get_doc("Account Group", group_name)

		return self._account_group_docs[group_name]

	@staticmethod
	def get_report_type():
		raise NotImplementedError("get_report_type not implemented")
