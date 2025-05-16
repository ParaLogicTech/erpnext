import frappe
from frappe import _
from frappe.model.document import Document


class AccountGroup(Document):
	def validate(self):
		self.validate_root_level()
		self.validate_rows()

	def validate_root_level(self):
		"""Validate root level account group type."""
		if self.is_root_level:
			if self.report_type not in ['Profit and Loss', 'Balance Sheet']:
				frappe.throw(_("Root level Account Groups must be either 'Profit and Loss' or 'Balance Sheet'"))

			# Check if another root level group exists for this reporting type
			existing_root = frappe.db.get_value('Account Group',
				filters={
					'company': self.company,
					'is_root_level': 1,
					'report_type': self.report_type,
					'name': ['!=', self.name],
				},
				fieldname=['name', 'group_name'],
				as_dict=1,
			)

			if existing_root:
				frappe.throw(_("Another root level {0} already exists for report type {1}.").format(
					frappe.get_desk_link("Account Group", existing_root.name), self.report_type
				))

	def validate_rows(self):
		"""Validate rows for duplicates and clear irrelevant fields."""
		seen_accounts = set()
		seen_groups = set()

		for row in self.rows:
			if row.row_type == 'Account':
				# Clear irrelevant fields
				row.account_group = None
				row.section_name = None
				row.section_account_groups = None

				# Validate company and reporting type
				account = frappe.get_doc("Account", row.account)
				if account.is_group:
					frappe.throw(_("Row #{0}: Account {1} must not be group Account").format(
						row.idx, frappe.bold(row.account)
					))
				if account.report_type != self.report_type:
					frappe.throw(_("Row #{0}: Account {1} must of report type {2}").format(
						row.idx, frappe.bold(row.account), frappe.bold(self.report_type)
					))
				if account.company != self.company:
					frappe.throw(_("Row #{0}: Account {1} does not belong to Company {2}").format(
						row.idx, frappe.bold(row.account), frappe.bold(self.company)
					))

				# Check for duplicates
				if row.account in seen_accounts:
					frappe.throw(_("Row {0}: Account {1} appears multiple times").format(
						row.idx, frappe.bold(row.account)
					))
				seen_accounts.add(row.account)

			elif row.row_type == 'Account Group':
				# Clear irrelevant fields
				row.account = None
				row.section_name = None
				row.section_account_groups = None

				# Validate company and reporting type
				if row.account_group == self.name:
					frappe.throw(_("Row #{0}: Account Group must not be the same this one").format(row.idx))

				account_group = frappe.get_doc("Account Group", row.account_group)
				if account_group.report_type != self.report_type and not account_group.is_root_level:
					frappe.throw(_("Row #{0}: Account Group {1} must of reporting type {2}").format(
						row.idx, frappe.bold(row.account_group), frappe.bold(self.report_type)
					))
				if account_group.company != self.company:
					frappe.throw(_("Row #{0}: Account Group {1} does not belong to Company {2}").format(
						row.idx, frappe.bold(row.account_group), frappe.bold(self.company)
					))

				# Check for duplicates
				if row.account_group in seen_groups:
					frappe.throw(_("Row {0}: Account Group {1} appears multiple times").format(
						row.idx, row.account_group
					))
				seen_groups.add(row.account_group)

			elif row.row_type in ('Section Break', 'Section Group'):
				# Clear irrelevant fields
				row.account = None
				row.account_group = None

@frappe.whitelist()
def get_account_groups_for_balance_sheet(doctype, txt, searchfield, start, page_len, filters):
	company = filters.get("company")
	report_type = filters.get("report_type")
	exclude_name = filters.get("exclude_name")
	return frappe.db.sql("""
		SELECT name, group_name
		FROM `tabAccount Group`
		WHERE company = %s
		AND (report_type = %s OR is_root_level = 1)
		AND name != %s
		AND (name LIKE %s OR group_name LIKE %s)
		LIMIT %s OFFSET %s
	""", (company, report_type, exclude_name, f"%{txt}%", f"%{txt}%", page_len, start))
