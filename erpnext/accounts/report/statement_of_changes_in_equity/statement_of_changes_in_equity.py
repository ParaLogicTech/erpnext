# Copyright (c) 2026, ParaLogic and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.utils import flt, formatdate

from erpnext.accounts.doctype.account_group.account_group import (
	get_account_group_doc,
	get_accounts_in_account_group,
)
from erpnext.accounts.report.summarized_financial_statements import SummarizedFinancialReport

PCV = "Period Closing Voucher"
# Account Group whose rows are the equity lines (columns)
EQUITY_ACCOUNT_GROUP = "Equity Accounts"
# Equity accounts not under any equity line
OTHER_COLUMN = {"fieldname": "other_equity", "label": "Other Equity", "accounts": []}


def execute(filters=None):
	return StatementOfChangesInEquity(filters).run()


class StatementOfChangesInEquity(SummarizedFinancialReport):
	"""Rows come from the Report Root Account Group of Report Type Statement of Changes in Equity (Formula,
	Section Break, Section Total, Account, Account Group rows, and Variables, as in the Cash Flow Account Group);
	each equity line is a value field evaluated separately, so a formula like `profit` gives that line's profit.

	Formulas can use opening_balance, closing_balance, profit, contributions and period_closing, e.g.
	`closing_balance - running_grand_total` for the movements the lines above do not explain."""

	def setup_fields(self):
		# Like the Summarized Balance Sheet, the period runs from the start of the year to the Report Date
		self.filters.from_date = self.filters.year_start_date
		self.filters.to_date = self.filters.report_date

		self.equity_columns = fetch_equity_columns(self.filters.company)
		if not self.equity_columns:
			frappe.throw(_("No Equity accounts found for {0}").format(self.filters.company))

		self.value_fields = frappe._dict()
		for col in self.equity_columns + [OTHER_COLUMN]:
			self.value_fields[col["fieldname"]] = frappe._dict(
				{**col, "from_date": self.filters.from_date, "to_date": self.filters.to_date}
			)

		self.account_map = {acc: col["fieldname"] for col in self.equity_columns for acc in col["accounts"]}
		self.profit_column = get_profit_column(self.filters.company, self.equity_columns)
		self.movements = get_movements(self.filters, self.account_map, self.profit_column)

	def run(self):
		self.validate_filters()
		data = self.get_data()

		for row in data:
			if any(row.get(f) is not None for f in self.value_fieldnames) and row.value_type in ("Currency", "Float"):
				row["total_display"] = sum(flt(row.get(f"{f}_display")) for f in self.value_fieldnames)

		columns = list(self.equity_columns)
		if any(abs(flt(row.get(f"{OTHER_COLUMN['fieldname']}_display"))) >= 0.005 for row in data):
			columns.append(OTHER_COLUMN)

		return self.get_columns(columns), data

	def get_account_totals(self, all_accounts):
		"""Period movement of an Account / Account Group row, shown under the equity line the account belongs to."""
		account_totals = {}
		if not all_accounts:
			return account_totals

		conditions, values = get_gl_conditions(self.filters)
		values.update(
			{"accounts": list(all_accounts), "from_date": self.filters.from_date, "to_date": self.filters.to_date, "pcv": PCV}
		)
		rows = frappe.db.sql(
			f"""
			select gl.account, acc.root_type, sum(gl.credit - gl.debit) as amount
			from `tabGL Entry` gl
			inner join `tabAccount` acc on acc.name = gl.account
			where {conditions} and gl.account in %(accounts)s
				and gl.posting_date between %(from_date)s and %(to_date)s
				and gl.voucher_type != %(pcv)s
			group by gl.account, acc.root_type
			""",
			values,
			as_dict=1,
		)
		for row in rows:
			if row.root_type in ("Income", "Expense"):
				fieldname = self.profit_column
			else:
				fieldname = self.account_map.get(row.account, OTHER_COLUMN["fieldname"])
			totals = frappe._dict({f: 0 for f in self.value_fieldnames})
			totals[fieldname] = flt(row.amount)
			account_totals[row.account] = totals

		return account_totals

	def extend_eval_context(self, context):
		super().extend_eval_context(context)
		for key, amounts in self.movements.items():
			context[key] = flt(amounts.get(context.fieldname))
		context["is_profit_column"] = context.fieldname == self.profit_column

	def get_row(self, d, *args, **kwargs):
		row = super().get_row(d, *args, **kwargs)
		# Descriptions may use {from_date} and {to_date}, e.g. "As at {to_date}"
		row["account_display"] = (
			row["account_display"]
			.replace("{from_date}", formatdate(self.filters.from_date, "d MMMM yyyy"))
			.replace("{to_date}", formatdate(self.filters.to_date, "d MMMM yyyy"))
		)
		return row

	def get_columns(self, equity_columns):
		columns = [{"label": _("Particulars"), "fieldname": "account_display", "fieldtype": "Data", "width": 280}]
		for col in equity_columns:
			columns.append(
				{"label": _(col["label"]), "fieldname": f"{col['fieldname']}_display", "fieldtype": "Float", "width": 160}
			)
		columns.append({"label": _("Total equity"), "fieldname": "total_display", "fieldtype": "Float", "width": 170})
		return columns

	@staticmethod
	def get_report_type():
		return "Statement of Changes in Equity"


def fetch_equity_columns(company):
	"""Equity lines from the rows of the Equity Accounts Account Group, in order,
	each with all the accounts it resolves to."""
	if not frappe.db.exists("Account Group", {"name": EQUITY_ACCOUNT_GROUP, "company": company}):
		frappe.throw(
			_("Please configure Account Group {0} for {1}").format(frappe.bold(EQUITY_ACCOUNT_GROUP), company)
		)

	columns = []
	for row in get_account_group_doc(EQUITY_ACCOUNT_GROUP).rows:
		if row.row_type == "Account Group" and row.account_group:
			name = row.account_group
			label = get_account_group_doc(name).group_name or name
			accounts = list(get_accounts_in_account_group(name))
		elif row.row_type == "Account" and row.account:
			name = row.account
			label, accounts = name, [name]
		else:
			continue
		fieldname = re.sub(r"\W+", "_", name.lower()).strip("_")
		columns.append({"fieldname": fieldname, "label": label, "accounts": accounts})
	return columns


def get_profit_column(company, equity_columns):
	"""Column that also carries profit not yet closed to equity: the one holding the P&L accounts
	or the Period Closing Voucher's closing account."""
	closing_account = frappe.db.get_value(
		PCV, {"company": company, "docstatus": 1}, "closing_account_head", order_by="posting_date desc"
	)
	pl_accounts = set(
		frappe.get_all(
			"Account", filters={"company": company, "root_type": ("in", ["Income", "Expense"])}, pluck="name"
		)
	)
	for col in equity_columns:
		if closing_account in col["accounts"] or pl_accounts.intersection(col["accounts"]):
			return col["fieldname"]
	return equity_columns[-1]["fieldname"]


def get_gl_conditions(filters):
	finance_book = frappe.get_cached_value("Company", filters.company, "default_finance_book")
	values = {"company": filters.company, "finance_book": finance_book or ""}
	conditions = """gl.company = %(company)s
		and (gl.finance_book in (%(finance_book)s, '') or gl.finance_book is null)"""
	return conditions, values


def get_equity_balances(filters, account_map, date_condition, values):
	"""Credit-minus-debit of each equity column for the given date condition."""
	conditions, base_values = get_gl_conditions(filters)
	rows = frappe.db.sql(
		f"""
		select gl.account, sum(gl.credit - gl.debit) as amount
		from `tabGL Entry` gl
		inner join `tabAccount` acc on acc.name = gl.account
		where {conditions} and acc.root_type = 'Equity' and {date_condition}
		group by gl.account
		""",
		{**base_values, **values},
		as_dict=1,
	)
	balances = {}
	for row in rows:
		fieldname = account_map.get(row.account, OTHER_COLUMN["fieldname"])
		balances[fieldname] = balances.get(fieldname, 0) + flt(row.amount)
	return balances


def get_pl_net(filters, extra_condition, values):
	"""Credit-minus-debit on Income and Expense accounts, i.e. profit."""
	conditions, base_values = get_gl_conditions(filters)
	return flt(
		frappe.db.sql(
			f"""
			select sum(gl.credit - gl.debit)
			from `tabGL Entry` gl
			inner join `tabAccount` acc on acc.name = gl.account
			where {conditions} and acc.root_type in ('Income', 'Expense') and {extra_condition}
			""",
			{**base_values, **values},
		)[0][0]
	)


def get_contributions(filters, account_map):
	"""Non-closing vouchers in the period that only credit a single equity line."""
	conditions, values = get_gl_conditions(filters)
	values.update({"from_date": filters.from_date, "to_date": filters.to_date, "pcv": PCV})
	rows = frappe.db.sql(
		f"""
		select gl.voucher_type, gl.voucher_no, gl.account, sum(gl.credit - gl.debit) as amount
		from `tabGL Entry` gl
		inner join `tabAccount` acc on acc.name = gl.account
		where {conditions} and acc.root_type = 'Equity'
			and gl.posting_date between %(from_date)s and %(to_date)s
			and gl.voucher_type != %(pcv)s
		group by gl.voucher_type, gl.voucher_no, gl.account
		""",
		values,
		as_dict=1,
	)

	per_voucher = {}
	for row in rows:
		fieldname = account_map.get(row.account, OTHER_COLUMN["fieldname"])
		amounts = per_voucher.setdefault((row.voucher_type, row.voucher_no), {})
		amounts[fieldname] = amounts.get(fieldname, 0) + flt(row.amount)

	contributions = {}
	for amounts in per_voucher.values():
		amounts = {k: v for k, v in amounts.items() if abs(v) >= 0.005}
		# A voucher moving value between two equity lines is a reserve transfer, not a contribution
		if len(amounts) == 1:
			fieldname, amount = next(iter(amounts.items()))
			if amount > 0:
				contributions[fieldname] = contributions.get(fieldname, 0) + amount

	return contributions


def get_movements(filters, account_map, profit_column):
	"""Amounts per equity column, available by name in the Account Group's formulas and variables."""
	before_from = {"from_date": filters.from_date}
	upto_to = {"to_date": filters.to_date}
	in_period = {"from_date": filters.from_date, "to_date": filters.to_date, "pcv": PCV}
	period = "gl.posting_date between %(from_date)s and %(to_date)s"

	# Unclosed P&L sits in the Income/Expense accounts, so it is added to the profit column
	opening = get_equity_balances(filters, account_map, "gl.posting_date < %(from_date)s", before_from)
	opening[profit_column] = opening.get(profit_column, 0) + get_pl_net(
		filters, "gl.posting_date < %(from_date)s", before_from
	)

	closing = get_equity_balances(filters, account_map, "gl.posting_date <= %(to_date)s", upto_to)
	closing[profit_column] = closing.get(profit_column, 0) + get_pl_net(
		filters, "gl.posting_date <= %(to_date)s", upto_to
	)

	profit = {profit_column: get_pl_net(filters, f"{period} and gl.voucher_type != %(pcv)s", in_period)}

	# Period Closing Voucher moves profit out of the P&L into its closing account
	period_closing = get_equity_balances(
		filters, account_map, f"{period} and gl.voucher_type = %(pcv)s", in_period
	)
	period_closing[profit_column] = period_closing.get(profit_column, 0) + get_pl_net(
		filters, f"{period} and gl.voucher_type = %(pcv)s", in_period
	)

	# Dividends, reserve transfers and other movements are left to the Account Group's formulas,
	# e.g. `closing_balance - running_grand_total` for whatever the lines above do not explain
	return {
		"opening_balance": opening,
		"closing_balance": closing,
		"profit": profit,
		"contributions": get_contributions(filters, account_map),
		"period_closing": period_closing,
	}
