# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
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
		data = []

		for acc in accounts:
			row = {
				"account": acc.name,
				"account_number": acc.account_number,
				"account_name": acc.account_name,
			}

			groups = self.account_group_mapping.get(acc["name"], [])

			for i in range(1, self.max_groups + 1):
				row[f"account_group_{i}"] = groups[i-1] if i-1 < len(groups) else None

			# Check for recent GL Entry if unmapped
			row["recent_unmapped"] = ""

			if not groups:
				recent_entry = frappe.db.exists(
					"GL Entry",
					{
						"account": acc["name"],
						"posting_date": [">=", frappe.utils.add_days(frappe.utils.nowdate(), -90)]
					}
				)
				row["recent_unmapped"] = _("Needs Mapping") if recent_entry else ""
			data.append(row)

		return data

	def get_accounts(self):
		condtions = [
			"is_group = 0",
		]

		if self.filters.company:
			condtions.append("company = %(company)s")
		if self.filters.report_type:
			condtions.append("report_type = %(report_type)s")
		if self.filters.root_type:
			condtions.append("root_type = %(root_type)s")

		condtions_str = " AND ".join(condtions)

		return frappe.db.sql(f"""
			SELECT name, account_number, account_name, root_type, lft, rgt
			FROM `tabAccount`
			WHERE {condtions_str}
			ORDER BY lft
		""", self.filters, as_dict=True)

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
