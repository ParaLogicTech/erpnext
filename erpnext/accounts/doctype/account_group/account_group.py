import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import comma_or, clean_whitespace


class AccountGroup(Document):
	def validate(self):
		self.validate_group_level()
		self.validate_root_type()
		self.validate_rows()
		self.cleanup()

	def validate_group_level(self):
		"""Validate root level account group type."""
		if self.group_level == "Report Root":
			report_types = ['Profit and Loss', 'Balance Sheet', 'Cash Flow', 'Ratios']
			if self.report_type not in report_types:
				frappe.throw(_("Root level Account Groups must be either {0}").format(comma_or(report_types)))

			# Check if another root level group exists for this reporting type
			existing_root = frappe.db.get_value('Account Group',
				filters={
					'company': self.company,
					'group_level': "Report Root",
					'report_type': self.report_type,
					'name': ['!=', self.name],
				},
				fieldname=['name', 'group_name'],
				as_dict=1,
			)

			if existing_root:
				frappe.throw(_("Another Report Root level {0} already exists for report type {1}.").format(
					frappe.get_desk_link("Account Group", existing_root.name), self.report_type
				))

		if self.group_level in ("Fixed Asset Root", "Fixed Asset Category"):
			if self.report_type != "Balance Sheet":
				frappe.throw(_("Report Type must be {0} for Group Level {1}").format(
					frappe.bold(_("Balance Sheet")),
					frappe.bold(self.group_level),
				))
			if self.root_type != "Asset":
				frappe.throw(_("Root Type must be {0} for Group Level {1}").format(
					frappe.bold(_("Asset")),
					frappe.bold(self.group_level),
				))

		if self.group_level == "Fixed Asset Root":
			existing_root = frappe.db.get_value(
				'Account Group',
				filters={
					'company': self.company,
					'group_level': "Fixed Asset Root",
					'report_type': self.report_type,
					'name': ['!=', self.name],
				},
				fieldname=['name', 'group_name'],
				as_dict=1,
			)

			if existing_root:
				frappe.throw(_("Another Fixed Asset Root {0} already exists").format(
					frappe.get_desk_link("Account Group", existing_root.name)
				))

			# Child account groups must be Fixed Asset Category
			for row in self.rows:
				if row.row_type == "Account Group" and row.account_group:
					row_group_level = frappe.get_cached_value("Account Group", row.account_group, "group_level")
					if row_group_level != "Fixed Asset Category":
						frappe.throw(_("Row #{0}: {1} must be {2} for Fixed Asset Root's Child Account Group").format(
							row.idx, frappe.bold(row.account_group), frappe.bold(_("Fixed Asset Category"))
						))

	def validate_root_type(self):
		pnl_root_types = ("Income", "Expense")
		bs_root_types = ("Asset", "Liability", "Equity")

		if self.report_type == "Profit and Loss":
			if self.root_type not in pnl_root_types:
				frappe.throw(_("Root Type must be either {0} for {1} Account Group").format(
					comma_or(pnl_root_types), self.report_type
				))

		elif self.report_type in ("Balance Sheet", "Cash Flow"):
			if self.root_type not in bs_root_types:
				frappe.throw(_("Root Type must be either {0} for {1} Account Group").format(
					comma_or(bs_root_types), self.report_type
				))

	def validate_rows(self):
		"""Validate rows for duplicates and clear irrelevant fields."""
		seen_accounts = set()
		seen_groups = set()

		for row in self.rows:
			if row.row_type != "Account":
				row.account = None
			if row.row_type != "Account Group":
				row.account_group = None
			if row.row_type not in ("Section Total", "Formula"):
				row.options = None
			if row.row_type != "Formula":
				row.value_type = "Currency"

			if row.row_type == 'Account':
				# Validate company and reporting type
				account = frappe.get_doc("Account", row.account)
				if account.is_group:
					frappe.throw(_("Row #{0}: Account {1} must not be group Account").format(
						row.idx, frappe.bold(row.account)
					))
				if self.report_type in ("Profit and Loss", "Balance Sheet") and account.report_type != self.report_type:
					frappe.throw(_("Row #{0}: Account {1} must be of report type {2}").format(
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
				# Validate company and reporting type
				if row.account_group == self.name:
					frappe.throw(_("Row #{0}: Account Group must not be the same this one").format(row.idx))

				account_group = frappe.get_doc("Account Group", row.account_group)
				if (
					self.report_type in ("Profit and Loss", "Balance Sheet")
					and account_group.report_type != self.report_type
					and not (account_group.group_level == "Report Root" and account_group.report_type == "Profit and Loss")
				):
					frappe.throw(_("Row #{0}: Account Group {1} must of Report Type {2}").format(
						row.idx, frappe.bold(row.account_group), frappe.bold(self.report_type)
					))
				if account_group.company != self.company:
					frappe.throw(_("Row #{0}: Account Group {1} does not belong to Company {2}").format(
						row.idx, frappe.bold(row.account_group), frappe.bold(self.company)
					))

				# Check for duplicates
				if row.account_group in seen_groups:
					frappe.throw(_("Row {0}: Account Group {1} is duplicated").format(
						row.idx, row.account_group
					))
				seen_groups.add(row.account_group)

	def cleanup(self):
		for d in self.rows:
			d.section_name = clean_whitespace(d.section_name)

		for d in self.variables:
			d.variable_name = clean_whitespace(d.variable_name)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def account_group_query(doctype, txt, searchfield, start, page_len, filters):
	from erpnext.controllers.queries import get_fields
	from frappe.desk.reportview import get_filters_cond

	fields = get_fields("Account Group", ["name", "report_type", "root_type"])
	report_type = filters.pop("report_type", None)

	report_type_condition = ""
	if report_type:
		report_type_condition = "AND (report_type = %(report_type)s OR (group_level = 'Report Root' and report_type = 'Profit and Loss'))"

	return frappe.db.sql("""
		SELECT {fields}
		FROM `tabAccount Group`
		WHERE
			name LIKE %(txt)s
			{report_type_condition}
			{fcond}
		order by
			if(locate(%(_txt)s, name), locate(%(_txt)s, name), 99999),
			modified desc,
			name
		LIMIT %(start)s, %(page_len)s
	""".format(**{
		"fields": ", ".join(fields),
		"fcond": get_filters_cond(doctype, filters, []).replace('%', '%%'),
		"report_type_condition": report_type_condition,
	}), {
		'txt': "%%%s%%" % txt,
		'_txt': txt.replace("%", ""),
		'start': start,
		'page_len': page_len,
		'report_type': report_type,
	})
