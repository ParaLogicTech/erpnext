import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
	return UnbilledStockBalance(filters).run()


class UnbilledStockBalance:
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters)

	def run(self):
		self.validate_filters()
		self.set_default_unbilled_stock_account()
		self.get_data()
		self.prepare_data()
		columns = self.get_columns()

		return columns, self.rows

	def validate_filters(self):
		self.filters.from_date = getdate(self.filters.from_date)
		self.filters.to_date = getdate(self.filters.to_date)

		if self.filters.from_date > self.filters.to_date:
			frappe.throw(_("From Date must be before To Date"))
	
	def set_default_unbilled_stock_account(self):
		self.all_unbilled_stock_accounts = set()
		default_stock_delivered_but_not_billed = frappe.db.get_value("Company", self.filters.company, "stock_delivered_but_not_billed")
		if default_stock_delivered_but_not_billed:
			self.all_unbilled_stock_accounts.add(default_stock_delivered_but_not_billed)

	def get_data(self):

		dn_conditions = self.get_conditions("dn")
		dn_conditions_str = "and {0}".format(" and ".join(dn_conditions)) if dn_conditions else ""

		self.delivery_note_data = frappe.db.sql(
			f"""
			select
				dn.name as delivery_note,
				dn.company,
				i.unbilled_stock_account,
				dn.is_return,
				dn.return_against
			from `tabDelivery Note Item` i
			inner join `tabDelivery Note` dn on dn.name = i.parent
			where
				dn.docstatus = 1
				and i.unbilled_stock_account != ''
				and i.unbilled_stock_account is not null
				{dn_conditions_str}
			group by dn.name, i.unbilled_stock_account
			order by dn.posting_date, dn.posting_time, dn.name
		""", self.filters, as_dict=1)

		si_conditions = self.get_conditions("si")
		si_conditions_str = "and {0}".format(" and ".join(si_conditions)) if si_conditions else ""

		self.sales_invoice_data = frappe.db.sql(f"""
			select
				si.name as sales_invoice,
				si.company,
				i.unbilled_stock_account,
				sum(i.unbilled_stock_value) as billed_stock_value,
				i.delivery_note
			from `tabSales Invoice Item` i
			inner join `tabSales Invoice` si on si.name = i.parent
			where
				si.docstatus = 1
				and i.unbilled_stock_account != ''
				and i.unbilled_stock_account is not null
				and i.delivery_note != ''
				and i.delivery_note is not null
				{si_conditions_str}
			group by si.name, i.delivery_note, i.unbilled_stock_account
		""", self.filters, as_dict=1)

		self.journal_entry_data = []
		je_conditions = self.get_conditions("tje")
		je_conditions_str = "and {0}".format(" and ".join(je_conditions)) if je_conditions else ""
		
		if self.all_unbilled_stock_accounts:
			self.journal_entry_data = frappe.db.sql(
				f"""
				select
					tje.name as journal_entry,
					tje.company,
					sum(tjea.debit_in_account_currency) as debit,
					sum(tjea.credit_in_account_currency) as credit,
					tjea.account as unbilled_stock_account,
					tjea.reference_type,
					tjea.reference_name
				from `tabJournal Entry` tje
				inner join `tabJournal Entry Account` tjea on tje.name = tjea.parent
				where
					tje.docstatus = 1
					and tjea.account in %(accounts)s
					{je_conditions_str}
				group by tje.name, tjea.account
				order by tje.posting_date, tje.name
			""", {
					**self.filters,
					"accounts": self.all_unbilled_stock_accounts
				}, as_dict=1)

		self.all_delivery_notes = set()
		self.delivery_notes = set()
		self.delivery_returns = {}
		self.delivery_note_unbilled_accounts = {}

		for d in self.delivery_note_data:
			self.all_delivery_notes.add(d.delivery_note)
			if d.is_return:
				self.delivery_returns[d.delivery_note] = d.return_against
			else:
				self.delivery_notes.add(d.delivery_note)

			self.delivery_note_unbilled_accounts.setdefault(d.delivery_note, set()).add(d.unbilled_stock_account)
			self.all_unbilled_stock_accounts.add(d.unbilled_stock_account)

		self.delivery_note_gle_data = []
		if self.delivery_note_unbilled_accounts and self.all_unbilled_stock_accounts:
			self.delivery_note_gle_data = frappe.db.sql("""
				select
					posting_date,
					voucher_no as delivery_note,
					company,
					account as unbilled_stock_account,
					sum(debit) as debit,
					sum(credit) as credit
				from `tabGL Entry`
				where
					voucher_type = 'Delivery Note'
					and voucher_no in %(delivery_notes)s
					and account in %(unbilled_stock_accounts)s
				group by voucher_no, account
				order by posting_date, voucher_no, account
			""", {
				"delivery_notes": self.all_delivery_notes,
				"unbilled_stock_accounts": self.all_unbilled_stock_accounts,
			}, as_dict=1)

	def get_conditions(self, prefix):
		conditions = []

		if self.filters.company:
			conditions.append(f"{prefix}.company = %(company)s")
		if self.filters.from_date:
			conditions.append(f"{prefix}.posting_date >= %(from_date)s")
		if self.filters.to_date:
			conditions.append(f"{prefix}.posting_date <= %(to_date)s")

		return conditions

	def prepare_data(self):
		row_map = {}

		# delivered
		for gle in self.delivery_note_gle_data:
			if gle.delivery_note in self.delivery_returns:
				continue
			if gle.unbilled_stock_account not in self.delivery_note_unbilled_accounts.get(gle.delivery_note, set()):
				continue

			key = (gle.delivery_note, gle.unbilled_stock_account)
			if key not in row_map:
				row_map[key] = self.get_row_template(gle)

			row_obj = row_map[key]
			row_obj.delivered_value += gle.debit - gle.credit

		# returned
		for gle in self.delivery_note_gle_data:
			if gle.delivery_note not in self.delivery_returns:
				continue
			if gle.unbilled_stock_account not in self.delivery_note_unbilled_accounts.get(gle.delivery_note, set()):
				continue

			key = (gle.delivery_note, gle.unbilled_stock_account)
			return_against = self.delivery_returns[gle.delivery_note]
			if return_against and (return_against, gle.unbilled_stock_account) in row_map:
				key = (return_against, gle.unbilled_stock_account)
				row_obj = row_map[key]
			elif key in row_map:
				row_obj = row_map[key]
			else:
				row_obj = row_map[key] = self.get_row_template(gle)

			row_obj.returned_value += gle.credit - gle.debit

		# billed
		for sid in self.sales_invoice_data:
			key = (sid.delivery_note, sid.unbilled_stock_account)
			if key in row_map:
				row_obj = row_map[key]
			else:
				row_obj = row_map[key] = self.get_row_template(sid)

			row_obj.billed_value += flt(sid.billed_stock_value)
		
		# Journal Entry
		for je in self.journal_entry_data:
			key = (je.journal_entry, je.unbilled_stock_account)
			if key in row_map:
				row_obj = row_map[key]
			else:
				row_obj = row_map[key] = self.get_row_template(je)
			row_obj.delivered_value += je.debit
			row_obj.billed_value += je.credit

		# post process
		for d in row_map.values():
			d.difference = d.delivered_value - d.returned_value - d.billed_value

		self.rows = list(row_map.values())

	@staticmethod
	def get_row_template(data):
		return frappe._dict({
			"posting_date": data.posting_date,
			"delivery_note": data.delivery_note,
			"sales_invoice": data.sales_invoice,
			"journal_entry": data.journal_entry,
			"unbilled_stock_account": data.unbilled_stock_account,
			"company": data.company,
			"delivered_value": 0,
			"returned_value": 0,
			"billed_value": 0,
			"difference": 0,
		})

	def get_columns(self):
		return [
			{
				"label": _("Date"),
				"fieldname": "posting_date",
				"fieldtype": "Date",
				"width": 80,
			},
			{
				"label": _("Delivery Note"),
				"fieldname": "delivery_note",
				"fieldtype": "Link",
				"options": "Delivery Note",
				"width": 150,
			},
			{
				"label": _("Sales Invoice"),
				"fieldname": "sales_invoice",
				"fieldtype": "Link",
				"options": "Sales Invoice",
				"width": 150,
			},
			{
				"label": _("Journal Entry"),
				"fieldname": "journal_entry",
				"fieldtype": "Link",
				"options": "Journal Entry",
				"width": 150,
			},
			{
				"label": _("Unbilled Stock Account"),
				"fieldname": "unbilled_stock_account",
				"fieldtype": "Link",
				"options": "Account",
				"width": 150,
			},
			{
				"label": _("Delivered Value"),
				"fieldname": "delivered_value",
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"width": 120,
			},
			{
				"label": _("Returned Value"),
				"fieldname": "returned_value",
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"width": 120,
			},
			{
				"label": _("Billed Value"),
				"fieldname": "billed_value",
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"width": 120,
			},
			{
				"label": _("Unbilled / WIP"),
				"fieldname": "difference",
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"width": 120,
			},
		]
