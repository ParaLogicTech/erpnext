# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from erpnext import get_default_company


def execute(filters=None):
	return AccountGroupMappingReport(filters).run()


class AccountGroupMappingReport:
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})

	def run(self):
		self.validate_filters()
		self.account_groups = self.get_account_groups()
		self.account_group_names = [g.name for g in self.account_groups]
		self.account_group_mapping = self.get_account_group_mapping(self.account_group_names)

		self.max_groups = max((len(groups) for groups in self.account_group_mapping.values()), default=1)

		return self.get_columns(), self.get_rows()

	def validate_filters(self):
		if not self.filters.company:
			self.filters.company = get_default_company()
		if not self.filters.company:
			frappe.throw(_("Company is mandatory"))
		if not self.filters.report_type:
			frappe.throw(_("Report Type is mandatory"))

	def get_account_groups(self):
		return frappe.get_all(
			"Account Group",
			filters={"company": self.filters.company, "report_type": self.filters.report_type},
			fields=["name", "report_type", "root_type"],
			order_by="name"
		)

	def get_account_group_mapping(self, account_group_names):
		mapping = {}

		rows = []
		if account_group_names:
			rows = frappe.get_all(
				"Account Group Row",
				filters={
					"parent": ["in", account_group_names],
					"row_type": "Account"
				},
				fields=["account", "parent"]
			)

		for d in rows:
			mapping.setdefault(d.account, []).append(d.parent)

		return mapping

	def get_rows(self):
		accounts = self.get_accounts()
		account_names = [d.name for d in accounts]

		gl_map = self.get_gl_map(account_names)

		data = []

		for acc in accounts:
			gl_obj = gl_map.get(acc.name, {})
			mapped_groups = self.account_group_mapping.get(acc.name, [])

			if self.filters.filter_without_entries and not gl_obj and not mapped_groups:
				continue

			row = frappe._dict({
				"account": acc.name,
				"account_number": acc.account_number,
				"account_name": acc.account_name,
				"company": self.filters.company,
			})

			if gl_obj:
				row.update({
					"debit": flt(gl_obj.get("debit")),
					"credit": flt(gl_obj.get("credit")),
					"diff": flt(gl_obj.get("debit")) - flt(gl_obj.get("credit")),
				})

			for i in range(1, self.max_groups + 1):
				row[f"account_group_{i}"] = mapped_groups[i-1] if i-1 < len(mapped_groups) else None

			data.append(row)

		return data

	def get_accounts(self):
		conditions = [
			"is_group = 0",
		]

		if self.filters.company:
			conditions.append("company = %(company)s")
		if self.filters.report_type:
			conditions.append("report_type = %(report_type)s")
		if self.filters.root_type:
			conditions.append("root_type = %(root_type)s")

		conditions_str = " AND ".join(conditions)

		return frappe.db.sql(f"""
			SELECT name, account_number, account_name, root_type, lft, rgt
			FROM `tabAccount`
			WHERE {conditions_str}
			ORDER BY lft
		""", self.filters, as_dict=True)

	def get_gl_map(self, accounts):
		if not accounts:
			return {}

		conditions = [
			"account in %(accounts)s"
		]
		if self.filters.from_date:
			conditions.append("posting_date >= %(from_date)s")
		if self.filters.to_date:
			conditions.append("posting_date <= %(to_date)s")

		conditions_str = " AND ".join(conditions)

		gl_data = frappe.db.sql(f"""
			select account, sum(debit) as debit, sum(credit) as credit
			from `tabGL Entry`
			where {conditions_str}
			group by account
		""", {
			"accounts": accounts,
			"from_date": self.filters.from_date,
			"to_date": self.filters.to_date,
		}, as_dict=True)

		gl_map = {}
		for d in gl_data:
			gl_map[d.account] = d

		return gl_map

	def get_columns(self):
		columns = [
			{
				"label": _("Account"),
				"fieldname": "account",
				"fieldtype": "Link",
				"options": "Account",
				"width": 350,
			},
		]

		for idx in range(1, self.max_groups + 2):
			columns.append({
				"label": _("Account Group {0}").format(idx),
				"fieldname": f"account_group_{idx}",
				"fieldtype": "Link",
				"options": "Account Group",
				"get_query": {
					"filters": {
						"company": self.filters.company,
						"report_type": self.filters.report_type,
					}
				},
				"width": 200,
				"editable": 1,
				"account_group_idx": idx,
			})

		columns += [
			{
				"label": _("Debit"),
				"fieldname": "debit",
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"width": 120,
			},
			{
				"label": _("Credit"),
				"fieldname": "credit",
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"width": 120,
			},
			{
				"label": _("Net"),
				"fieldname": "diff",
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"width": 120,
			},
		]

		return columns


@frappe.whitelist()
def update_account_group_mapping(account, old_group, new_group):
	if not account:
		frappe.throw(_("Account is required."))

	if old_group == new_group:
		return

	if old_group and old_group != new_group:
		old_group_doc = frappe.get_doc("Account Group", old_group)
		old_group_doc.rows = [r for r in old_group_doc.rows if not (r.row_type == "Account" and r.account == account)]
		# Reset idx for all rows
		for i, r in enumerate(old_group_doc.rows):
			r.idx = i + 1
		old_group_doc.save()

	if new_group:
		new_group_doc = frappe.get_doc("Account Group", new_group)
		if not any(r.row_type == "Account" and r.account == account for r in new_group_doc.rows):
			new_group_doc.append("rows", {
				"row_type": "Account",
				"account": account
			})
			new_group_doc.save()
