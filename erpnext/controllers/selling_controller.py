# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import cint, flt, cstr
from frappe import _
from erpnext.stock.get_item_details import get_bin_details
from erpnext.stock.utils import get_incoming_rate, has_valuation_read_permission
from erpnext.stock.get_item_details import get_target_warehouse_validation, item_has_product_bundle
from erpnext.stock.doctype.batch.batch import get_batch_qty, auto_select_and_split_batches
from erpnext.overrides.sales_person.sales_person_hooks import get_sales_person_commission_details
from erpnext.controllers.transaction_controller import TransactionController


class SellingController(TransactionController):
	selling_or_buying = "selling"

	def __setup__(self):
		if hasattr(self, "taxes"):
			self.flags.print_taxes_with_zero_amount = cint(frappe.get_cached_value("Print Settings", None,
				"print_taxes_with_zero_amount"))
			self.flags.show_inclusive_tax_in_print = self.is_inclusive_tax()

			self.print_templates = {
				"total": "templates/print_formats/includes/total.html",
				"taxes": "templates/print_formats/includes/taxes.html"
			}

	def get_feed(self):
		if self.get("customer_name") or self.get("customer"):
			return _("To {0} | {1} {2}").format(self.get("customer_name") or self.get("customer"), self.currency,
				self.get_formatted("grand_total"))

	def onload(self):
		super(SellingController, self).onload()

		if self.doctype in ("Sales Order", "Delivery Note", "Sales Invoice"):
			self.set_onload("is_internal_customer",
				frappe.get_cached_value("Customer", self.get("bill_to") or self.customer, "is_internal_customer"))

			for item in self.get("items"):
				item.update(get_bin_details(item.item_code, item.warehouse))
				if item.meta.has_field('actual_batch_qty'):
					if item.get('batch_no'):
						item.actual_batch_qty = get_batch_qty(item.batch_no, item.warehouse, item.item_code)
					else:
						item.actual_batch_qty = 0

		if self.docstatus == 0 and self.meta.get_field("currency"):
			self.calculate_taxes_and_totals()

	def validate(self):
		super(SellingController, self).validate()
		self.validate_bill_to()
		self.validate_items()
		self.validate_max_discount()
		self.validate_selling_price()
		self.set_qty_as_per_stock_uom()
		self.set_alt_uom_qty()
		self.set_po_nos()
		self.set_gross_profit()
		self.validate_for_duplicate_items()
		self.validate_target_warehouse()

	def before_update_after_submit(self):
		self.calculate_sales_team_contribution(self.get('base_net_total'))

	def get_party(self):
		party = self.get("customer")
		party_name = self.get("customer_name") if party else None
		return "Customer", party, party_name

	def get_billing_party(self):
		if self.get("bill_to"):
			return "Customer", self.get("bill_to"), self.get("bill_to_name")

		return super().get_billing_party()

	def set_missing_values(self, for_validate=False):
		super(SellingController, self).set_missing_values(for_validate)

		# set contact and address details for customer, if they are not mentioned
		self.set_missing_lead_customer_details()
		self.set_sales_person_details()
		self.set_price_list_and_item_details(for_validate=for_validate)

	def update_status_on_cancel(self):
		to_update = {}
		if self.meta.has_field("status"):
			to_update["status"] = "Cancelled"

		not_applicable_fields = ["billing_status", "delivery_status", "packing_status", "installation_status"]
		for f in not_applicable_fields:
			if self.meta.has_field(f):
				to_update[f] = "Not Applicable"

		if to_update:
			self.db_set(to_update)

	def set_missing_lead_customer_details(self):
		party_type, party = None, None

		if self.get("customer"):
			party_type = "Customer"
			party = self.customer
		elif self.doctype == "Quotation" and self.party_name:
			party_type = self.quotation_to
			party = self.party_name

		if party_type and party:
			from erpnext.accounts.party import _get_party_details

			party_details = _get_party_details(
				party=party,
				party_type=party_type,
				bill_to=self.get("bill_to"),
				ignore_permissions=self.flags.ignore_permissions,
				doctype=self.doctype,
				company=self.company,
				project=self.get('project'),
				payment_terms_template=self.get('payment_terms_template'),
				party_address=self.get("customer_address"),
				shipping_address=self.get("shipping_address_name"),
				company_address=self.get("company_address"),
				contact_person=self.get('contact_person'),
				has_stin=self.get("has_stin"),
				account=self.get('debit_to'),
				cost_center=self.get('cost_center'),
				posting_date=self.get('posting_date') or self.get('transaction_date'),
				delivery_date=self.get('delivery_date'),
				price_list=self.get('selling_price_list'),
				currency=self.get("currency"),
				transaction_type=self.get("transaction_type"),
				pos_profile=self.get("pos_profile"),
			)

			if not self.meta.get_field("sales_team"):
				party_details.pop("sales_team", None)

			self.update_if_missing(party_details, force_fields=self.force_party_fields)

	def set_sales_person_details(self):
		sales_team = self.get("sales_team") or []
		for d in sales_team:
			d.update(get_sales_person_commission_details(d.sales_person))

	def set_price_list_and_item_details(self, for_validate=False):
		self.set_price_list_currency("Selling")
		self.set_missing_item_details(for_validate=for_validate)

	def calculate_taxes_and_totals(self):
		super().calculate_taxes_and_totals()
		self.calculate_commission()
		self.calculate_sales_team_contribution(self.get('base_net_total'))

	def remove_shipping_charge(self):
		if self.shipping_rule:
			shipping_rule = frappe.get_doc("Shipping Rule", self.shipping_rule)
			existing_shipping_charge = self.get("taxes", {
				"doctype": "Sales Taxes and Charges",
				"charge_type": "Actual",
				"account_head": shipping_rule.account,
				"cost_center": shipping_rule.cost_center
			})
			if existing_shipping_charge:
				self.get("taxes").remove(existing_shipping_charge[-1])
				self.calculate_taxes_and_totals()

	def calculate_commission(self):
		if self.meta.get_field("commission_rate"):
			self.round_floats_in(self, ["base_net_total", "commission_rate"])
			if self.commission_rate > 100.0:
				frappe.throw(_("Commission rate cannot be greater than 100"))

			self.total_commission = flt(self.base_net_total * self.commission_rate / 100.0,
				self.precision("total_commission"))

	def validate_max_discount(self):
		for d in self.get("items"):
			if d.item_code:
				discount = flt(frappe.get_cached_value("Item", d.item_code, "max_discount"))

				if discount and flt(d.discount_percentage) > discount:
					frappe.throw(_("Maximum discount for Item {0} is {1}%").format(d.item_code, discount))

	def set_qty_as_per_stock_uom(self):
		for d in self.get("items"):
			if d.meta.get_field("stock_qty"):
				if not d.conversion_factor and d.item_code:
					frappe.throw(_("Row {0}: Conversion Factor is mandatory").format(d.idx))
				d.stock_qty = flt(flt(d.qty) * flt(d.conversion_factor), 6)

	def set_alt_uom_qty(self):
		for d in self.get("items"):
			if d.meta.get_field("alt_uom_qty"):
				if not d.alt_uom:
					d.alt_uom_size = 1.0
				d.alt_uom_qty = flt(flt(d.stock_qty) * flt(d.alt_uom_size), d.precision("alt_uom_qty"))

	def validate_selling_price(self):
		def throw_message(idx, item_name, rate, ref_rate_field):
			frappe.throw(_("""Row #{}: Selling rate for item {} is lower than its {}. Selling rate should be atleast {}""")
				.format(idx, item_name, ref_rate_field, rate))

		if not frappe.get_cached_value("Selling Settings", None, "validate_selling_price"):
			return

		if hasattr(self, "is_return") and self.is_return:
			return

		for it in self.get("items"):
			if not it.item_code:
				continue

			last_purchase_rate, is_stock_item = frappe.get_cached_value("Item", it.item_code, ["last_purchase_rate", "is_stock_item"])
			last_purchase_rate_in_sales_uom = last_purchase_rate / (it.conversion_factor or 1)
			if flt(it.base_rate) < flt(last_purchase_rate_in_sales_uom):
				throw_message(it.idx, frappe.bold(it.item_name), last_purchase_rate_in_sales_uom, "last purchase rate")

			last_valuation_rate = frappe.db.sql("""
				SELECT valuation_rate FROM `tabStock Ledger Entry` WHERE item_code = %s
				AND warehouse = %s AND valuation_rate > 0
				ORDER BY posting_date DESC, posting_time DESC, creation DESC LIMIT 1
				""", (it.item_code, it.warehouse))
			if last_valuation_rate:
				last_valuation_rate_in_sales_uom = last_valuation_rate[0][0] / (it.conversion_factor or 1)
				if is_stock_item and flt(it.base_rate) < flt(last_valuation_rate_in_sales_uom):
					throw_message(it.idx, frappe.bold(it.item_name), last_valuation_rate_in_sales_uom, "valuation rate")

	def get_item_list(self):
		il = []
		for d in self.get("items"):
			if d.qty is None:
				frappe.throw(_("Row {0}: Qty is mandatory").format(d.idx))

			if item_has_product_bundle(d.item_code):
				for p in self.get("packed_items"):
					if p.parent_detail_docname == d.name and p.parent_item == d.item_code:
						# the packing details table's qty is already multiplied with parent's qty
						il.append(frappe._dict({
							'warehouse': p.warehouse or d.warehouse,
							'item_code': p.item_code,
							'qty': flt(p.qty),
							'uom': p.uom,
							'batch_no': cstr(p.batch_no).strip(),
							'packing_slip': p.get("packing_slip"),
							'serial_no': cstr(p.serial_no).strip(),
							'name': d.name,
							'target_warehouse': p.target_warehouse,
							'company': self.company,
							'voucher_type': self.doctype,
							'allow_zero_valuation': d.allow_zero_valuation_rate,
							'delivery_note': d.get('delivery_note')
						}))
			else:
				il.append(frappe._dict({
					'warehouse': d.warehouse,
					'item_code': d.item_code,
					'qty': d.stock_qty,
					'uom': d.uom,
					'stock_uom': d.stock_uom,
					'conversion_factor': d.conversion_factor,
					'batch_no': cstr(d.get("batch_no")).strip(),
					'packing_slip': d.get("packing_slip"),
					'serial_no': cstr(d.get("serial_no")).strip(),
					'name': d.name,
					'target_warehouse': d.target_warehouse,
					'company': self.company,
					'voucher_type': self.doctype,
					'allow_zero_valuation': d.allow_zero_valuation_rate,
					'delivery_note': d.get('delivery_note'),
					'delivery_note_item': d.get('delivery_note_item'),
					'sales_invoice_item': d.get('sales_invoice_item')
				}))
		return il

	@frappe.whitelist()
	def auto_select_batches(self):
		if (self.doctype == "Delivery Note" or self.get('update_stock')) and not self.get('is_return'):
			auto_select_and_split_batches(self, 'warehouse', additional_group_fields=[
				"sales_order", "sales_order_item",
				"delivery_note", "delivery_note_item",
				"sales_invoice", "sales_invoice_item",
				"quotation",
			])
			self.run_method("calculate_taxes_and_totals")

	def get_already_delivered_qty(self, current_docname, so, sales_order_item):
		delivered_via_dn = frappe.db.sql("""select sum(qty) from `tabDelivery Note Item`
			where sales_order_item = %s and docstatus = 1
			and sales_order = %s
			and parent != %s""", (sales_order_item, so, current_docname))

		delivered_via_si = frappe.db.sql("""select sum(si_item.qty)
			from `tabSales Invoice Item` si_item, `tabSales Invoice` si
			where si_item.parent = si.name and si.update_stock = 1
			and si_item.sales_order_item = %s and si.docstatus = 1
			and si_item.sales_order = %s
			and si.name != %s""", (sales_order_item, so, current_docname))

		total_delivered_qty = (flt(delivered_via_dn[0][0]) if delivered_via_dn else 0) \
			+ (flt(delivered_via_si[0][0]) if delivered_via_si else 0)

		return total_delivered_qty

	def get_so_qty_and_warehouse(self, sales_order_item):
		so_item = frappe.db.sql("""select qty, warehouse from `tabSales Order Item`
			where name = %s and docstatus = 1""", sales_order_item, as_dict=1)
		so_qty = so_item and flt(so_item[0]["qty"]) or 0.0
		so_warehouse = so_item and so_item[0]["warehouse"] or ""
		return so_qty, so_warehouse

	def check_sales_order_on_hold_or_close(self):
		for d in self.get("items"):
			if d.get('sales_order') and not d.get('delivery_note'):
				status = frappe.db.get_value("Sales Order", d.get('sales_order'), "status", cache=1)
				if status == "Closed" and not cint(self.get('is_return')):
					frappe.throw(_("Row #{0}: {1} is {2}").format(d.idx, frappe.get_desk_link("Sales Order", d.get('sales_order')), status))
				if status == "On Hold":
					frappe.throw(_("Row #{0}: {1} is {2}").format(d.idx, frappe.get_desk_link("Sales Order", d.get('sales_order')), status))

	def update_reserved_qty(self):
		so_map = {}
		for d in self.get("items"):
			if d.sales_order_item:
				if self.doctype == "Delivery Note" and d.sales_order:
					so_map.setdefault(d.sales_order, []).append(d.sales_order_item)
				elif self.doctype == "Sales Invoice" and d.sales_order and self.update_stock:
					so_map.setdefault(d.sales_order, []).append(d.sales_order_item)

		for so, so_item_rows in so_map.items():
			if so and so_item_rows:
				sales_order = frappe.get_doc("Sales Order", so)

				if sales_order.status in ["Closed", "Cancelled"] and not frappe.flags.ignored_closed_or_disabled:
					frappe.throw(_("{0} {1} is cancelled or closed").format(_("Sales Order"), so),
						frappe.InvalidStatusError)

				sales_order.update_reserved_qty(so_item_rows)

	def update_stock_ledger(self):
		if not frappe.flags.do_not_update_reserved_qty:
			self.update_reserved_qty()

		sl_entries = []
		for d in self.get_item_list():
			if frappe.db.get_value("Item", d.item_code, "is_stock_item", cache=1) and flt(d.qty):
				return_rate = 0
				return_dependency = []

				if cint(self.is_return) and self.docstatus==1:
					delivery_note = self.return_against if self.doctype == "Delivery Note" else d.get('delivery_note')
					if d.get('delivery_note_item') and delivery_note:
						return_dependency = [{
							"dependent_voucher_type": "Delivery Note",
							"dependent_voucher_no": delivery_note,
							"dependent_voucher_detail_no": d.delivery_note_item,
							"dependency_type": "Rate"
						}]
						return_rate = self.get_incoming_rate_for_sales_return(voucher_detail_no=d.delivery_note_item,
							against_document_type="Delivery Note", against_document=delivery_note)
					elif self.doctype == "Sales Invoice" and d.get('sales_invoice_item') and self.get('return_against')\
							and frappe.db.get_value("Sales Invoice", self.return_against, 'update_stock', cache=1):
						return_dependency = [{
							"dependent_voucher_type": "Sales Invoice",
							"dependent_voucher_no": self.return_against,
							"dependent_voucher_detail_no": d.sales_invoice_item,
							"dependency_type": "Rate"
						}]
						return_rate = self.get_incoming_rate_for_sales_return(voucher_detail_no=d.sales_invoice_item,
							against_document_type="Sales Invoice", against_document=self.return_against)
					else:
						return_rate = self.get_incoming_rate_for_sales_return(item_code=d.item_code,
							warehouse=d.warehouse, batch_no=d.batch_no)

				# On cancellation or if return entry submission, make stock ledger entry for
				# target warehouse first, to update serial no values properly

				if d.warehouse and ((not cint(self.is_return) and self.docstatus==1)
					or (cint(self.is_return) and self.docstatus==2)):
						sl_entries.append(self.get_sl_entries(d, {
							"actual_qty": -1*flt(d.qty),
							"incoming_rate": return_rate,
							"is_transfer": cint(bool(d.get("target_warehouse"))),
						}))

				target_warehouse_dependency = []
				if d.target_warehouse:
					if self.docstatus == 1:
						target_warehouse_dependency = [{
							"dependent_voucher_type": self.doctype,
							"dependent_voucher_no": self.name,
							"dependent_voucher_detail_no": d.name,
							"dependency_type": "Amount",
						}]

					if self.is_return:
						target_warehouse_dependency, return_dependency = return_dependency, target_warehouse_dependency
						if target_warehouse_dependency:
							target_warehouse_dependency[0]['dependency_qty_filter'] = 'Positive'

					target_warehouse_sle = self.get_sl_entries(d, {
						"actual_qty": flt(d.qty),
						"warehouse": d.target_warehouse,
						"dependencies": target_warehouse_dependency,
						"is_transfer": 1,
					})

					if self.docstatus == 1:
						if not cint(self.is_return):
							args = frappe._dict({
								"item_code": d.item_code,
								"warehouse": d.warehouse,
								"batch_no": d.batch_no,
								"posting_date": self.posting_date,
								"posting_time": self.posting_time,
								"qty": -1*flt(d.qty),
								"serial_no": d.serial_no,
								"company": d.company,
								"voucher_type": d.voucher_type,
								"voucher_no": d.name,
								"allow_zero_valuation": d.allow_zero_valuation
							})
							target_warehouse_sle.update({
								"incoming_rate": get_incoming_rate(args)
							})
						else:
							target_warehouse_sle.update({
								"outgoing_rate": return_rate
							})
					sl_entries.append(target_warehouse_sle)

				if d.warehouse and ((not cint(self.is_return) and self.docstatus==2)
					or (cint(self.is_return) and self.docstatus==1)):
						sl_entries.append(self.get_sl_entries(d, {
							"actual_qty": -1*flt(d.qty),
							"incoming_rate": return_rate,
							"dependencies": return_dependency,
							"is_transfer": cint(bool(d.get("target_warehouse"))),
						}))
		self.make_sl_entries(sl_entries)

	def remove_partial_packing_slip_for_return(self):
		if not self.get("is_return"):
			return

		packing_slip_map = {}
		for d in self.get("items"):
			if d.get("packing_slip") and d.get("packing_slip_item"):
				packing_slip_map.setdefault(d.packing_slip, {}).setdefault(d.packing_slip_item, 0)
				packing_slip_map[d.packing_slip][d.packing_slip_item] += -1 * d.qty

		to_remove = []
		for packing_slip, returned_qty_map in packing_slip_map.items():
			packed_qty_map = dict(frappe.db.sql("""
				select name, qty
				from `tabPacking Slip Item`
				where parent = %s and docstatus = 1 and qty != 0
			""", packing_slip))

			if returned_qty_map != packed_qty_map:
				to_remove.append(packing_slip)

		if to_remove:
			for d in self.get("items"):
				if d.get("packing_slip") and d.packing_slip in to_remove:
					d.packing_slip = None
					d.packing_slip_item = None

	def set_po_nos(self):
		if self.doctype in ("Delivery Note", "Sales Invoice") and hasattr(self, "items"):
			sales_orders = list(set([d.get('sales_order') for d in self.items if d.get('sales_order')]))
			if sales_orders:
				po_nos = frappe.db.sql_list("""
					select distinct po_no
					from `tabSales Order`
					where name in %s and ifnull(po_no, '') != ''
					order by transaction_date
				""", [sales_orders])
				if po_nos:
					self.po_no = ', '.join(po_nos)
					if len(self.po_no) > 140:
						self.po_no = self.po_no[:137] + "..."

	def set_gross_profit(self):
		if self.doctype == "Sales Order":
			for item in self.items:
				item.gross_profit = flt(((item.base_net_rate - item.valuation_rate) * item.stock_qty), self.precision("amount", item))

	def validate_bill_to(self):
		if not self.meta.get_field('bill_to'):
			return
		if not self.get('bill_to'):
			self.bill_to = self.customer
			self.bill_to_name = self.customer_name

	def validate_for_duplicate_items(self):
		check_list, chk_dupl_itm = [], []
		if cint(frappe.get_cached_value("Selling Settings", None, "allow_multiple_items")):
			return

		for d in self.get('items'):
			if self.doctype == "Sales Invoice":
				e = [d.item_code, d.description, d.warehouse, d.sales_order or d.delivery_note, d.batch_no or '']
				f = [d.item_code, d.description, d.sales_order or d.delivery_note]
			elif self.doctype == "Delivery Note":
				e = [d.item_code, d.description, d.warehouse, d.sales_order or d.sales_invoice, d.batch_no or '']
				f = [d.item_code, d.description, d.sales_order or d.sales_invoice]
			elif self.doctype in ["Sales Order", "Quotation"]:
				e = [d.item_code, d.description, d.warehouse, '']
				f = [d.item_code, d.description]

			if frappe.get_cached_value("Item", d.item_code, "is_stock_item"):
				if e in check_list:
					frappe.throw(_("Note: Item {0} entered multiple times").format(d.item_code))
				else:
					check_list.append(e)
			else:
				if f in chk_dupl_itm:
					frappe.throw(_("Note: Item {0} entered multiple times").format(d.item_code))
				else:
					chk_dupl_itm.append(f)

	def validate_items(self):
		# validate items to see if they have is_sales_item enabled
		from erpnext.controllers.buying_controller import validate_item_type
		validate_item_type(self, "is_sales_item", "sales")

		from erpnext.stock.doctype.item.item import validate_end_of_life
		for d in self.get('items'):
			if d.item_code:
				item = frappe.get_cached_value("Item", d.item_code, ['has_variants', 'end_of_life', 'disabled'], as_dict=1)
				if not d.get('sales_order') and not d.get('delivery_note'):
					validate_end_of_life(d.item_code, end_of_life=item.end_of_life, disabled=item.disabled)

				if cint(item.has_variants):
					frappe.throw(_("Row #{0}: {1} is a template Item, please select one of its variants")
						.format(d.idx, frappe.bold(d.item_code)))

	def validate_target_warehouse(self):
		if frappe.get_meta(self.doctype + " Item").has_field("target_warehouse"):
			items = self.get("items") + (self.get("packed_items") or [])

			for d in items:
				if d.get("target_warehouse") and d.get("warehouse") == d.get("target_warehouse"):
					warehouse = frappe.bold(d.get("target_warehouse"))
					frappe.throw(_("Row {0}: Source Warehouse ({1}) and Target Warehouse ({2}) can not be same")
						.format(d.idx, warehouse, warehouse))

				if d.get('item_code'):
					target_warehouse_validation = get_target_warehouse_validation(d.item_code, self.transaction_type, self.company)

					if target_warehouse_validation:
						if target_warehouse_validation == "Mandatory" and not d.target_warehouse:
							frappe.throw(_("Row #{0}: Target Warehouse must be set for Item {1}").format(d.idx, d.item_code))
						if target_warehouse_validation == "Not Allowed" and d.target_warehouse:
							frappe.throw(_("Row #{0}: Target Warehouse must be not set for Item {1}").format(d.idx, d.item_code))

	def validate_transaction_type(self):
		super(SellingController, self).validate_transaction_type()

		if self.get('transaction_type'):
			if not frappe.get_cached_value("Transaction Type", self.transaction_type, 'selling'):
				frappe.throw(_("Transaction Type {0} is not allowed for sales transactions").format(frappe.bold(self.transaction_type)))

	def validate_project_customer(self):
		if self.project and self.customer:
			res = frappe.db.sql("""
				select name
				from `tabProject`
				where name = %s and (customer = %s or ifnull(customer,'') = '')
			""", (self.project, self.customer))
			if not res:
				frappe.throw(_("Customer {0} does not belong to project {1}").format(self.customer, self.project))

	def update_project_billing_and_sales(self):
		projects = []
		if self.get('project'):
			projects.append(self.get('project'))
		for d in self.items:
			if d.get('project'):
				projects.append(d.get('project'))

		projects = list(set(projects))
		for project in projects:
			doc = frappe.get_doc("Project", project)
			doc.validate_project_status_for_transaction(self)

			if self.doctype in ("Delivery Note", "Sales Invoice") and self.docstatus == 1:
				doc.validate_vehicle_not_received()

			if self.doctype == "Sales Invoice" and self.docstatus == 1:
				doc.validate_ready_to_close()

			doc.set_billing_and_delivery_status(update=True)
			doc.set_sales_amount(update=True)
			doc.set_gross_margin(update=True)
			doc.set_status(update=True)
			doc.notify_update()

	@frappe.whitelist()
	def set_rate_as_cost(self):
		if not has_valuation_read_permission():
			frappe.throw(_("You do not have permission to set rate as cost"))

		for item in self.items:
			if item.get("item_code"):
				item.rate = self.get_item_cost_rate(item)
				item.discount_percentage = 0
				item.margin_rate_or_amount = 0

		self.calculate_taxes_and_totals()

	def get_item_cost_rate(self, item):
		transaction_qty = flt(item.qty)

		if item.get("delivery_note") and item.get("delivery_note_item"):
			sle_totals = frappe.db.sql("""
				SELECT SUM(stock_value_difference) as stock_value_difference, SUM(actual_qty) as actual_qty
				FROM `tabStock Ledger Entry` 
				WHERE voucher_type = 'Delivery Note' AND voucher_no = %s AND voucher_detail_no = %s
			""", (item.delivery_note, item.delivery_note_item), as_dict=1)

			sle_totals = sle_totals[0] if sle_totals else None

			if sle_totals:
				qty = flt(sle_totals.actual_qty) or transaction_qty or 1
				cost_rate = flt(sle_totals.stock_value_difference) / qty
			else:
				cost_rate = 0

		else:
			from erpnext.stock.utils import get_incoming_rate
			args = frappe._dict({
				"item_code": item.item_code,
				"warehouse": item.warehouse,
				"batch_no": item.batch_no,
				"serial_no": item.serial_no,
				"posting_date": self.posting_date,
				"posting_time": self.posting_time,
				"qty": item.qty,
				"voucher_type": self.doctype,
				"voucher_no": self.name,
				"company": self.company
			})
			cost_rate = get_incoming_rate(args, raise_error_if_no_rate=False)

		return cost_rate


@frappe.whitelist()
def update_customer_name_from_master(doctype, name):
	from erpnext.accounts.party import get_party_name

	if doctype not in ("Quotation", "Sales Order", "Delivery Note", "Sales Invoice"):
		frappe.throw(_("DocType {0} not allowed").format(doctype))

	doc = frappe.get_doc(doctype, name)

	if doc.docstatus != 1:
		frappe.throw(_("{0} {1} is not submitted").format(doctype, name))

	doc.check_permission("submit")

	doc._doc_before_save = frappe.get_doc(doc.as_dict())

	if doc.doctype == "Quotation":
		party_type = doc.party_type
		party = doc.party_name
	else:
		party_type = "Customer"
		party = doc.get("customer")

	if party_type and party:
		doc.customer_name = get_party_name(party_type, party)
		doc.db_set("customer_name", doc.customer_name)

	if doc.get("bill_to"):
		doc.bill_to_name = get_party_name("Customer", doc.bill_to)
		doc.db_set("bill_to_name", doc.bill_to_name)

	if doc.meta.has_field("title"):
		doc.run_method("set_title")
		if doc.get("title"):
			doc.db_set("title", doc.get("title"))

	doc.notify_update()
	doc.save_version()
