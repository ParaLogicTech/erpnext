import frappe
import erpnext
from frappe import _, scrub, unscrub
from frappe.utils import flt, cint, cstr, getdate, get_first_day, get_year_start, add_years, get_year_ending
from erpnext import get_default_company
from erpnext.accounts.doctype.account_group.account_group import get_account_group_doc, get_accounts_in_account_group
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children, get_all_dimension_fields,
)
from erpnext.accounts.report.financial_statements import get_cost_centers_with_children


class SummarizedFinancialReport:
	def __init__(self, filters=None):
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

	@property
	def value_fieldnames(self):
		return list(self.value_fields.keys())

	def setup_fields(self):
		pass

	def validate_filters(self):
		if not self.filters.company:
			self.filters.company = get_default_company()
		if not self.filters.company:
			frappe.throw(_("Company is mandatory"))

		if self.filters.dimension_field and self.filters.dimension_field not in get_all_dimension_fields():
			frappe.throw(_("Invalid Dimension Field {0}").format(self.filters.dimension_field))

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

		rows = self.get_account_group_rows(self.current_account_group)

		if not is_root:
			totals = {k: 0 for k in self.value_fieldnames}
			for row in rows:
				if row.get('row_type') in ['Account', 'Account Group'] and not row.get('is_child'):
					for f in totals:
						totals[f] += flt(row.get(f))

			for f in self.value_fieldnames:
				totals[f"{f}_display"] = totals[f]

			rows.append(frappe._dict({
				'row_type': 'Total',
				'account_display': 'Total',
				'is_bold': 1,
				**totals
			}))

		return rows

	def get_root_account_group(self):
		return frappe.db.get_value(
			"Account Group",
			{
				"company": self.filters.get('company'),
				"group_level": "Report Root",
				"report_type": self.get_report_type(),
			},
			"name",
		)

	def get_account_group_rows(self, group_name):
		"""Aggregate account and group data for a given group."""
		data = []
		group = self.get_account_group_doc(group_name)
		group_root_type = group.root_type

		self.group_account_map = self.get_accounts_in_account_group(group, as_map=True)
		all_accounts = self.group_account_map.get(group.name, [])
		self.account_totals = self.get_account_totals(all_accounts)
		self.set_missing_account_zeroes(all_accounts)
		self.child_group_totals = self.get_child_group_totals(self.group_account_map)

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
				parent_row = self.get_row(
					row,
					totals=totals,
					group_root_type=group_root_type,
				)
				data.append(parent_row)

				if self.filters.tree_view:
					data += self.get_child_rows(row, root_value_multiplier=self.get_multiplier(parent_row))

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

	def get_accounts_in_account_group(self, account_group, as_map=False):
		return get_accounts_in_account_group(account_group, as_map=as_map, tree_view=self.filters.tree_view, cache="local")

	def get_child_group_totals(self, group_account_map):
		child_group_totals = {}

		for account_group, group_accounts in group_account_map.items():
			child_group_doc = self.get_account_group_doc(account_group)
			group_totals = self.get_group_totals(group_accounts)
			group_totals["root_type"] = child_group_doc.root_type
			child_group_totals[account_group] = group_totals

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

	def get_account_group_balance(self, account_group, to_date, dimension_field=None, dimension_value=None):
		if not to_date:
			return 0

		to_date = getdate(to_date)

		def generator():
			accounts = self.get_accounts_in_account_group(account_group, as_map=False)
			balance = self.get_gl_data(
				accounts,
				to_date=to_date,
				aggregate=True,
				grouped=False,
				dimension_field=dimension_field,
				dimension_value=dimension_value,
			)
			return flt(balance[0].debit) - flt(balance[0].credit) if balance else 0

		key = (account_group, to_date, cstr(dimension_field), cstr(dimension_value))
		if key not in self._get_account_group_balance:
			self._get_account_group_balance[key] = generator()

		return self._get_account_group_balance[key]

	def get_asset_additions_and_disposals(
		self,
		account_group,
		from_date,
		to_date,
		dimension_field=None,
		dimension_value=None,
	):
		template = frappe._dict({"additions": 0, "disposals": 0})
		if not to_date:
			return template

		to_date = getdate(to_date)
		from_date = getdate(from_date) if from_date else None

		def generator():
			out = template.copy()
			accounts = self.get_accounts_in_account_group(account_group, as_map=False)
			disposal_jvs = self.get_asset_disposal_jvs()

			gl_data = self.get_gl_data(
				accounts,
				from_date=from_date,
				to_date=to_date,
				aggregate=False,
				dimension_field=dimension_field,
				dimension_value=dimension_value,
			)
			for d in gl_data:
				is_disposal = d.voucher_type == "Sales Invoice" or (d.voucher_type == "Journal Entry" and d.voucher_no in disposal_jvs)

				if is_disposal:
					out["disposals"] += d.credit - d.debit
				else:
					out["additions"] += d.debit - d.credit

			return out

		key = (account_group, from_date, to_date, cstr(dimension_field), cstr(dimension_value))
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

	def get_net_profit_loss(self):
		return {f: 0 for f in self.value_fieldnames}

	def get_child_rows(self, parent_row, root_value_multiplier=1, indent=1):
		if not parent_row.account_group:
			return []

		parent_group = self.get_account_group_doc(parent_row.account_group)
		group_root_type = parent_group.root_type

		rows = []
		for row in parent_group.rows:
			if row.row_type == "Account":
				totals = self.account_totals.get(row.account) or {}
				rows.append(self.get_row(
					row,
					totals=totals,
					group_root_type=group_root_type,
					indent=indent,
					root_value_multiplier=root_value_multiplier,
				))
			elif row.row_type == "Account Group":
				totals = self.child_group_totals.get(row.account_group) or {}
				rows.append(self.get_row(
					row,
					totals=totals,
					group_root_type=group_root_type,
					indent=indent,
					root_value_multiplier=root_value_multiplier,
				))

				rows += self.get_child_rows(row, root_value_multiplier=root_value_multiplier, indent=indent + 1)

		return rows

	def get_row(
		self,
		d,
		totals=None,
		is_bold=False,
		group_root_type=None,
		indent=0,
		root_value_multiplier=None,
	):
		row = frappe._dict()

		no_values = True
		if totals is not None:
			no_values = False

		if not totals:
			totals = frappe._dict()

		if not no_values:
			for f in self.value_fieldnames:
				row[f] = totals.get(f)

		row["row_type"] = d.row_type
		row["account_display"] = d.section_name or ""
		row["root_type"] = totals.get("root_type") or group_root_type
		row["is_bold"] = cint(d.is_bold or is_bold)
		row["value_type"] = d.value_type or "Currency"
		row["format_precision"] = d.format_precision
		row["currency"] = erpnext.get_company_currency(self.filters.company)
		row["right_align"] = d.right_align
		row["indent"] = cint(indent)
		row["is_child"] = cint(indent) > 0

		if d.row_type == "Account":
			row["account"] = d.account
			row["account_display"] = row["account_display"] or d.account
		elif d.row_type == "Account Group":
			row["account_group"] = d.account_group
			row["account_display"] = row["account_display"] or d.account_group

		row["group_level"] = d.row_type
		if d.row_type == "Account Group":
			row["group_level"] = frappe.get_cached_value("Account Group", d.account_group, "group_level")

		if not no_values:
			if row.value_type == "Data":
				for f in self.value_fieldnames:
					row[f"{f}_display"] = row[f]
			else:
				if root_value_multiplier:
					multiplier = root_value_multiplier
				else:
					multiplier = self.get_multiplier(row)

				for f in self.value_fieldnames:
					row[f"{f}_display"] = row[f] * multiplier if row[f] is not None else None

		return row

	def get_account_totals(self, all_accounts):
		raise NotImplementedError("get_account_totals not implemented")

	def set_missing_account_zeroes(self, all_accounts):
		for account in all_accounts:
			if not self.account_totals.get(account):
				self.account_totals[account] = frappe._dict({f: 0 for f in self.value_fieldnames})

	def _get_account_totals_data(self, all_accounts, gl_fields, dr_or_cr, aggregate=True, dimension_field=None):
		def accumulate(gle, group, fieldname):
			if dr_or_cr == "credit":
				diff = gle.credit - gle.debit
			else:
				diff = gle.debit - gle.credit

			group[fieldname] += diff

			if dimension_field:
				dimension_value = cstr(gle.get(dimension_field))
				dimension_values.add(dimension_value)
				dimension_key = self.get_dimension_key(fieldname, dimension_value)

				group.setdefault(dimension_key, 0)
				group[dimension_key] += diff

		template = frappe._dict({f: 0 for f in self.value_fieldnames})

		account_totals = {}
		dimension_values = set()

		if aggregate:
			for fieldname, field_info in gl_fields.items():
				gl_data = self.get_gl_data(
					all_accounts,
					from_date=field_info.from_date,
					to_date=field_info.to_date,
					aggregate=aggregate,
					dimension_field=dimension_field,
				)

				for d in gl_data:
					group = account_totals.setdefault(d.account, template.copy())
					accumulate(d, group, fieldname)
		else:
			from_date = min([f.from_date for f in gl_fields.values()])
			to_date = max([f.to_date for f in gl_fields.values()])

			gl_data = self.get_gl_data(
				all_accounts,
				from_date=from_date,
				to_date=to_date,
				aggregate=aggregate,
				dimension_field=dimension_field,
			)

			for d in gl_data:
				if d.account not in account_totals:
					account_totals[d.account] = template.copy()

				group = account_totals[d.account]

				for fieldname, field_info in gl_fields.items():
					if field_info.from_date <= d.posting_date <= field_info.to_date:
						accumulate(d, group, fieldname)

		return frappe._dict({
			"account_totals": account_totals,
			"dimension_values": dimension_values,
		})

	def get_gl_data(
		self,
		accounts,
		to_date,
		from_date=None,
		aggregate=False,
		grouped=True,
		dimension_field=None,
		dimension_value=None,
	):
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

		additional_dimension_condition = ""
		if dimension_field and dimension_value is not None:
			if dimension_value:
				additional_dimension_condition = f"and {dimension_field} = {frappe.db.escape(dimension_value)}"
			else:
				additional_dimension_condition = f"and ({dimension_field} = '' or {dimension_field} is null)"

		fields = []
		group_by = ""
		order_by = ""

		if aggregate:
			fields += [
				"sum(debit) as debit",
				"sum(credit) as credit",
			]

			if grouped:
				fields.append("account")
				group_by = "GROUP BY account"

				if dimension_field:
					fields.append(dimension_field)
					group_by += ", " + dimension_field
		else:
			fields += [
				"account",
				"debit",
				"credit",
				"posting_date",
				"voucher_type",
				"voucher_no",
			]

			if dimension_field:
				fields.append(self.filters.dimension_field)

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
				{additional_dimension_condition}
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

	def get_multiplier(self, row):
		multiplier = self.get_display_value_multiplier(row)
		if row.reverse_sign:
			multiplier = multiplier * -1

		return multiplier

	def get_display_value_multiplier(self, row):
		return 1

	@staticmethod
	def get_account_group_doc(group_name):
		return get_account_group_doc(group_name, cache="local")

	@staticmethod
	def get_account_details(all_accounts):
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

	@staticmethod
	def get_dimension_key(fieldname, dimension_value):
		return f"{fieldname}_dim_{scrub(dimension_value)}"

	@staticmethod
	def get_dimension_label(dimension_field, dimension_value):
		if not dimension_value:
			return _("No {0}").format(unscrub(dimension_field))

		if dimension_field == "cost_center":
			return frappe.get_cached_value("Cost Center", dimension_value, "cost_center_name")
		else:
			return dimension_value

	@staticmethod
	def get_report_type():
		raise NotImplementedError("get_report_type not implemented")
