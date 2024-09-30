
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import getdate, add_days, formatdate, today
from frappe.model.document import Document
from datetime import date
from erpnext.controllers.item_variant import ItemTemplateCannotHaveStock
from erpnext.accounts.utils import get_fiscal_year


class StockFreezeError(frappe.ValidationError): pass


exclude_from_linked_with = True


class StockLedgerEntry(Document):
	def autoname(self):
		"""
		Temporarily name doc for fast insertion
		name will be changed using autoname options (in a scheduled job)
		"""
		self.name = frappe.generate_hash(txt="", length=10)

	def validate(self):
		self.flags.ignore_submit_comment = True
		from erpnext.stock.utils import validate_warehouse_company
		self.validate_mandatory()
		self.validate_item()
		self.validate_batch()
		self.validate_date()
		validate_warehouse_company(self.warehouse, self.company)
		self.scrub_posting_time()
		self.validate_and_set_fiscal_year()
		self.block_transactions_against_group_warehouse()

	def before_submit(self):
		self.validate_dependency()
		self.check_stock_frozen_date()

		if not self.get("via_landed_cost_voucher"):
			from erpnext.stock.doctype.serial_no.serial_no import process_serial_no
			process_serial_no(self)

		self.set_serial_no_table()

	def on_submit(self):
		if not self.get("via_landed_cost_voucher") and not self.get("skip_serial_no_ledger_validation"):
			from erpnext.stock.doctype.serial_no.serial_no import validate_serial_no_ledger
			validate_serial_no_ledger(self.serial_no, self.item_code, self.voucher_type, self.voucher_no, self.company)

	def validate_mandatory(self):
		mandatory = ['warehouse','posting_date','voucher_type','voucher_no','company']
		for k in mandatory:
			if not self.get(k):
				frappe.throw(_("{0} is required").format(self.meta.get_label(k)))

		if self.voucher_type != "Stock Reconciliation" and not self.actual_qty:
			frappe.throw(_("Actual Qty is mandatory"))

	def validate_date(self):
		if not self.get("via_landed_cost_voucher") and getdate(self.posting_date) > getdate(today()) and self.is_cancelled == "No":
			frappe.throw(_("Stock cannot be created for a future date {0}").format(self.get_formatted('posting_date')))

	def validate_item(self):
		item_det = frappe.db.sql("""select name, item_name, has_batch_no, docstatus,
			is_stock_item, has_variants, stock_uom, create_new_batch
			from tabItem where name=%s""", self.item_code, as_dict=True)

		if not item_det:
			frappe.throw(_("Item {0} not found").format(self.item_code))

		item_det = item_det[0]

		if not item_det.is_stock_item:
			frappe.throw(_("Item {0} must be a stock Item").format(self.item_code))

		# check if batch number is required
		if self.is_cancelled == "No":
			batch_item = self.item_code if self.item_code == item_det.item_name else self.item_code + ": " + item_det.item_name

			if item_det.has_batch_no:
				if not self.batch_no:
					frappe.throw(_("Batch number is mandatory for Item {0}").format(frappe.bold(batch_item)))
				elif not frappe.db.get_value("Batch", {"item": self.item_code, "name": self.batch_no}):
					frappe.throw(_("{0} is not a valid Batch Number for Item {1}").format(
						self.batch_no, frappe.bold(batch_item)
					))

			elif not item_det.has_batch_no and self.batch_no:
				frappe.throw(_("Item {0} cannot have Batch").format(frappe.bold(batch_item)))

		if item_det.has_variants:
			frappe.throw(_("Stock cannot exist for Item {0} since has variants").format(self.item_code),
				ItemTemplateCannotHaveStock)

		self.stock_uom = item_det.stock_uom

	def validate_dependency(self):
		# this validation also prevents circular dependency when checking whether dependency reference exists
		if not self.dependencies:
			return

		dependency_map = {}
		for d in self.dependencies:
			dependency_key = (d.dependent_voucher_type, d.dependent_voucher_no, d.dependent_voucher_detail_no)
			if dependency_key in dependency_map:
				frappe.throw(_("Duplicate Stock Ledger Entry Dependency found"))

			dependency_map[dependency_key] = d

			if d.dependency_percentage <= 0:
				frappe.throw(_("Invalid Dependency Percentage {0} in Stock Ledger Entry")
					.format(frappe.format(d.dependency_percentage)))

		dependency_keys = list(dependency_map.keys())
		dependent_sles = frappe.db.sql("""
			select name, voucher_type, voucher_no, voucher_detail_no, actual_qty
			from `tabStock Ledger Entry`
			where (voucher_type, voucher_no, voucher_detail_no) in %s
				and name != %s
		""", [dependency_keys, self.name], as_dict=1)

		# qty filter, some voucher_detail_no may have multiple SLEs like Delivery Note return against DN with Target Warehouse
		filtered_dependent_sles = []
		for dep_sle in dependent_sles:
			dependency_key = (dep_sle.voucher_type, dep_sle.voucher_no, dep_sle.voucher_detail_no)
			dependency_details = dependency_map[dependency_key]

			if dependency_details.dependency_qty_filter == "Positive" and dep_sle.actual_qty <= 0:
				continue
			if dependency_details.dependency_qty_filter == "Negative" and dep_sle.actual_qty >= 0:
				continue

			filtered_dependent_sles.append(dep_sle)

		# for each dependency there must be exactly one SLE
		if len(filtered_dependent_sles) != len(dependency_keys):
			frappe.throw(_("Invalid reference in Stock Ledger Entry Dependency"))

	def check_stock_frozen_date(self):
		stock_frozen_upto = frappe.get_cached_value('Stock Settings', None, 'stock_frozen_upto') or ''
		if stock_frozen_upto:
			stock_auth_role = frappe.get_cached_value('Stock Settings', None,'stock_auth_role')
			if getdate(self.posting_date) <= getdate(stock_frozen_upto) and not stock_auth_role in frappe.get_roles():
				frappe.throw(_("Stock transactions before {0} are frozen").format(formatdate(stock_frozen_upto)), StockFreezeError)

		stock_frozen_upto_days = int(frappe.get_cached_value('Stock Settings', None, 'stock_frozen_upto_days') or 0)
		if stock_frozen_upto_days:
			stock_auth_role = frappe.get_cached_value('Stock Settings', None,'stock_auth_role')
			older_than_x_days_ago = (add_days(getdate(self.posting_date), stock_frozen_upto_days) <= date.today())
			if older_than_x_days_ago and not stock_auth_role in frappe.get_roles():
				frappe.throw(_("Not allowed to update stock transactions older than {0}").format(stock_frozen_upto_days), StockFreezeError)

	def scrub_posting_time(self):
		if not self.posting_time or self.posting_time == '00:0':
			self.posting_time = '00:00'

	def validate_batch(self):
		if self.batch_no and self.voucher_type != "Stock Entry":
			expiry_date = frappe.db.get_value("Batch", self.batch_no, "expiry_date")
			if expiry_date:
				if getdate(self.posting_date) > getdate(expiry_date):
					frappe.throw(_("Batch {0} of Item {1} has expired.").format(self.batch_no, self.item_code))

	def validate_and_set_fiscal_year(self):
		if not self.fiscal_year:
			self.fiscal_year = get_fiscal_year(self.posting_date, company=self.company)[0]
		else:
			from erpnext.accounts.utils import validate_fiscal_year
			validate_fiscal_year(self.posting_date, self.fiscal_year, self.company,
				self.meta.get_label("posting_date"), self)

	def block_transactions_against_group_warehouse(self):
		from erpnext.stock.utils import is_group_warehouse
		is_group_warehouse(self.warehouse)

	def set_serial_no_table(self):
		from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos
		serial_nos = get_serial_nos(self.serial_no)

		self.serial_numbers = []
		for serial_no in serial_nos:
			self.append('serial_numbers', {'serial_no': serial_no})


def on_doctype_update():
	if not frappe.db.has_index('tabStock Ledger Entry', 'posting_sort_index'):
		frappe.db.commit()
		frappe.db.add_index("Stock Ledger Entry",
			fields=["posting_date", "posting_time", "creation"],
			index_name="posting_sort_index")

	frappe.db.add_index("Stock Ledger Entry", ["voucher_no", "voucher_type"])
	frappe.db.add_index("Stock Ledger Entry", ["item_code", "warehouse"])
	frappe.db.add_index("Stock Ledger Entry", ["batch_no", "item_code", "warehouse"])
