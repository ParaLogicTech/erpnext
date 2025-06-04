# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def execute(filters=None):
	return AccountGroupMappingReport(filters).run()

class AccountGroupMappingReport:
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})
		self.company = self.filters.get("company")
		self.report_type = self.filters.get("report_type")
		self.root_type = self.filters.get("root_type")

	def run(self):
		self.validate_filters()
		return self.get_columns(), self.get_data()

	def validate_filters(self):
		if not self.company:
			frappe.throw(_("Company filter is required"))

	def get_account_groups(self):
		filters = {"company": self.company, "report_type": self.report_type}
		return frappe.get_all(
			"Account Group",
			filters=filters,
			fields=["name", "group_name", "report_type", "root_type"],
			order_by="group_name"
		)

	def get_leaf_accounts(self):
		filters = {**self.filters, "is_group": 0}

		where_clauses = []
		args = []
		for key, value in filters.items():
			where_clauses.append(f"{key}=%s")
			args.append(value)

		where = " AND ".join(where_clauses)
		return frappe.db.sql(
			f"""
			SELECT name, account_number, account_name, root_type, lft, rgt
			FROM `tabAccount`
			WHERE {where}
			ORDER BY lft
			""", tuple(args), as_dict=True
		)

	def get_account_group_mappings(self, group_names):
		mapping = {}

		for group in group_names:
			rows = frappe.get_all(
				"Account Group Row",
				filters={"parent": group, "row_type": "Account"},
				fields=["account"]
			)
			for r in rows:
				mapping.setdefault(r["account"], []).append(group)
		return mapping

	def get_columns(self):
		columns = [
			{
				"label": _("Account Number"),
				"fieldname": "account_number",
				"fieldtype": "Data",
				"width": 100
			},
			{
				"label": _("Account Name"),
				"fieldname": "account_name",
				"fieldtype": "Data",
				"width": 250
			},
			{
				"label": _("Unmapped & Recent"),
				"fieldname": "recent_unmapped",
				"fieldtype": "Data",
				"width": 130
			},
		]

		self.account_groups = self.get_account_groups()
		self.group_names = [g.name for g in self.account_groups]
		self.account_group_mappings = self.get_account_group_mappings(self.group_names)
		max_groups = max((len(groups) for groups in self.account_group_mappings.values()), default=1)

		for i in range(1, max_groups + 2):
			columns.append({
				"label": _(f"Account Group {i}"),
				"fieldname": f"account_group_{i}",
				"fieldtype": "Link",
				"options": "Account Group",
				"get_query": {
					"filters": {
						"company": self.company,
						"report_type": self.report_type,
					}
				},
				"width": 160,
				"editable": 1,
				"align": "left"
			})

		return columns

	def get_data(self):
		accounts = self.get_leaf_accounts()
		data = []
		max_groups = len([c for c in self.get_columns() if c["fieldname"].startswith("account_group_")])

		for acc in accounts:
			row = {
				"account_number": acc["account_number"],
				"account_name": acc["account_name"],
				"account": acc["name"]
			}

			groups = self.account_group_mappings.get(acc["name"], [])

			for i in range(1, max_groups + 1):
				row[f"account_group_{i}"] = groups[i-1] if i-1 < len(groups) else ""

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
