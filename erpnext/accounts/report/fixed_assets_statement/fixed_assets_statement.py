import frappe
import erpnext
from frappe import _, scrub
from frappe.utils import flt, format_date
from erpnext.accounts.report.summarized_balance_sheet.summarized_balance_sheet import SummarizedBalanceSheet


def execute(filters=None):
	return FixedAssetsStatement(filters).run()


class FixedAssetsStatement(SummarizedBalanceSheet):
	date_format = "dd MMMM y"

	def setup_fields(self):
		self.value_fields = frappe._dict({
			"asset_opening": frappe._dict({
				"to_date": self.filters.prev_year_end,
				"is_gl_value": 1,
			}),
			"asset_additions": frappe._dict({
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
				"is_gl_value": 1,
			}),
			"asset_disposals": frappe._dict({
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
				"is_gl_value": 1,
			}),
			"asset_closing": frappe._dict({
				"to_date": self.filters.report_date,
				"is_gl_value": 1,
			}),
			"dep_opening": frappe._dict({
				"to_date": self.filters.prev_year_end,
				"is_gl_value": 1,
			}),
			"dep_charges": frappe._dict({
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
				"is_gl_value": 1,
			}),
			"dep_disposals": frappe._dict({
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
				"is_gl_value": 1,
			}),
			"dep_closing": frappe._dict({
				"to_date": self.filters.report_date,
				"is_gl_value": 1,
			}),
			"nbv_opening": frappe._dict({
				"to_date": self.filters.prev_year_end,
				"is_gl_value": 1,
			}),
			"nbv_closing": frappe._dict({
				"to_date": self.filters.report_date,
				"is_gl_value": 1,
			}),
		})

	def run(self):
		self.validate_filters()
		data = self.get_data()
		rows = self.transpose_data(data)

		return self.get_columns(data), rows

	def get_root_account_group(self):
		root_group = frappe.db.get_value(
			"Account Group",
			{
				"company": self.filters.get('company'),
				"is_fixed_asset_root": 1,
				"report_type": self.get_report_type(),
			},
			"name",
		)

		if not root_group:
			frappe.throw(_("Please configure Fixed Asset Root Account Group"))

		return root_group

	def get_account_totals(self, all_accounts):
		template = frappe._dict({f: 0 for f in self.value_fieldnames})

		account_details = self.get_account_details(all_accounts)

		opening_gl_totals = self.get_gl_data(
			all_accounts,
			to_date=self.filters.prev_year_end,
			aggregate=True,
		)

		ytd_gl_data = self.get_gl_data(
			all_accounts,
			from_date=self.filters.year_start_date,
			to_date=self.filters.report_date,
			aggregate=False,
		)

		disposal_jvs = set(frappe.db.sql_list("""
			select distinct journal_entry_for_scrap
			from `tabAsset`
			where journal_entry_for_scrap != '' and journal_entry_for_scrap is not null
		"""))

		account_totals = {}
		for d in opening_gl_totals:
			group = account_totals.setdefault(d.account, template.copy())
			group["nbv_opening"] += d.debit - d.credit
			group["nbv_closing"] += d.debit - d.credit

			account_type = account_details.get(d.account, {}).get("account_type")
			if account_type == "Accumulated Depreciation":
				group["dep_opening"] += d.debit - d.credit
				group["dep_closing"] += d.debit - d.credit
			else:
				group["asset_opening"] += d.debit - d.credit
				group["asset_closing"] += d.debit - d.credit

		for d in ytd_gl_data:
			if d.account in account_totals:
				group = account_totals[d.account]
			else:
				group = account_totals.setdefault(d.account, template.copy())

			group["nbv_closing"] += d.debit - d.credit

			account_type = account_details.get(d.account, {}).get("account_type")
			is_disposal = d.voucher_type == "Sales Invoice" or (d.voucher_type == "Journal Entry" and d.voucher_no in disposal_jvs)

			if account_type == "Accumulated Depreciation":
				group["dep_closing"] += d.debit - d.credit
				if is_disposal:
					group["dep_disposals"] += d.debit - d.credit
				else:
					group["dep_charges"] += d.debit - d.credit
			else:
				group["asset_closing"] += d.debit - d.credit
				if is_disposal:
					group["asset_disposals"] += d.debit - d.credit
				else:
					group["asset_additions"] += d.debit - d.credit

		return account_totals

	def transpose_data(self, data):
		company_currency = erpnext.get_company_currency(self.filters.company)

		row_map = frappe._dict({
			"asset_opening": {
				"description": _("As at {0}").format(format_date(self.filters.year_start_date, self.date_format)),
				"is_asset": 1,
				"format_link": 1,
				"from_date": self.filters.prev_year_start,
				"to_date": self.filters.prev_year_date,
			},
			"asset_additions": {
				"description": _("Additions"),
				"is_asset": 1,
			},
			"asset_disposals": {
				"description": _("Disposals"),
				"is_asset": 1,
			},
			"asset_transfers": {
				"description": _("Transfers"),
				"is_asset": 1,
			},
			"asset_closing": {
				"description": _("At {0}").format(format_date(self.filters.report_date, self.date_format)),
				"is_bold": 1,
				"is_asset": 1,
				"format_link": 1,
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
			},
			"dep_opening": {
				"description": _("As at {0}").format(format_date(self.filters.year_start_date, self.date_format)),
				"is_depreciation": 1,
				"format_link": 1,
				"from_date": self.filters.prev_year_start,
				"to_date": self.filters.prev_year_date,
			},
			"dep_charges": {
				"description": _("Charge for the Period"),
				"is_depreciation": 1,
			},
			"dep_disposals": {
				"description": _("On Disposals"),
				"is_depreciation": 1,
			},
			"dep_transfers": {
				"description": _("Transfers"),
				"is_depreciation": 1,
			},
			"dep_closing": {
				"description": _("At {0}").format(format_date(self.filters.report_date, self.date_format)),
				"is_bold": 1,
				"is_depreciation": 1,
				"format_link": 1,
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
			},
			"nbv_closing": {
				"description": _("At {0}").format(format_date(self.filters.report_date, self.date_format)),
				"is_bold": 1,
				"is_nbv": 1,
				"format_link": 1,
				"from_date": self.filters.year_start_date,
				"to_date": self.filters.report_date,
			},
			"nbv_opening": {
				"description": _("At {0}").format(format_date(self.filters.prev_year_end, self.date_format)),
				"is_nbv": 1,
				"format_link": 1,
				"from_date": self.filters.prev_year_start,
				"to_date": self.filters.prev_year_date,
			},
		})

		for fieldname, row_dict in row_map.items():
			row_dict["row_type"] = "Section Total"
			row_dict["value_type"] = "Currency"
			row_dict["currency"] = company_currency
			row_dict["fieldname"] = fieldname
			row_dict["total"] = 0

		for d in data:
			key = self.get_key(d)
			if not key:
				continue

			# transfers not implemented, show as 0
			for fieldname in ["asset_transfers", "dep_transfers"]:
				row_dict = row_map[fieldname]
				row_dict[key] = 0

			for fieldname in self.value_fieldnames:
				row_dict = row_map[fieldname]
				row_dict[key] = d[fieldname]
				row_dict["total"] += flt(d[fieldname])

				if row_dict.get("is_depreciation"):
					row_dict[key] *= -1

		for row_dict in row_map.values():
			if row_dict.get("is_depreciation"):
				row_dict["total"] *= -1

		rows = [
			{"description": _("Cost"), "row_type": "Section Break", "is_bold": 1},
			row_map["asset_opening"],
			row_map["asset_additions"],
			row_map["asset_disposals"],
			row_map["asset_transfers"],
			row_map["asset_closing"],

			{"row_type": "Section Break"},

			{"description": _("Depreciation"), "row_type": "Section Break", "is_bold": 1},
			row_map["dep_opening"],
			row_map["dep_charges"],
			row_map["dep_disposals"],
			row_map["dep_transfers"],
			row_map["dep_closing"],

			{"row_type": "Section Break"},

			{"description": _("Net Book Value"), "row_type": "Section Break", "is_bold": 1},
			row_map["nbv_closing"],

			{"row_type": "Section Break"},
			row_map["nbv_opening"],
		]

		return rows

	def get_key(self, d):
		if d.row_type == "Account":
			return f"acc_{scrub(d.account)}"
		elif d.row_type == "Account Group":
			return f"ag_{scrub(d.account_group)}"
		else:
			return None

	def get_columns(self, data):
		columns = [
			{
				"fieldname": "description",
				"label": _("Particulars"),
				"fieldtype": "Data",
				"width": 200,
			},
		]

		for d in data:
			key = self.get_key(d)
			if not key:
				continue

			columns.append({
				"fieldname": key,
				"label": d.account_display,
				"fieldtype": "Currency",
				"options": "currency",
				"width": 175,
				"is_value_field": 1,
				"account_group": d.account_group,
				"account": d.account,
			})

		columns.append({
			"fieldname": "total",
			"label": _("Total"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 175,
			"is_value_field": 1,
			"account_group": self.current_account_group,
		})

		return columns
