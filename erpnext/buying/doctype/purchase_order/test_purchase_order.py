# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import json
import unittest

import frappe
import frappe.defaults
from frappe.tests.utils import change_settings
from frappe.utils import add_days, flt, getdate, nowdate

from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice as make_pi_from_po
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from erpnext.buying.doctype.purchase_order.purchase_order import make_rm_stock_entry as make_subcontract_transfer_entry
from erpnext.controllers.transaction_controller import update_child_items
from erpnext.stock.doctype.batch.test_batch import make_new_batch
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.material_request.material_request import make_purchase_order
from erpnext.stock.doctype.material_request.test_material_request import make_material_request
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice as make_pi_from_pr
from erpnext.stock.doctype.stock_entry.test_stock_entry import make_stock_entry


class TestPurchaseOrder(unittest.TestCase):
	def test_make_purchase_receipt(self):
		po = create_purchase_order(do_not_submit=True)
		self.assertRaises(frappe.ValidationError, make_purchase_receipt, po.name)
		po.submit()

		pr = create_pr_against_po(po.name)
		self.assertEqual(len(pr.get("items")), 1)

	def test_ordered_qty(self):
		existing_ordered_qty = get_ordered_qty()

		po = create_purchase_order(do_not_submit=True)
		self.assertRaises(frappe.ValidationError, make_purchase_receipt, po.name)

		po.submit()
		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 10)

		create_pr_against_po(po.name)
		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 6)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 4)

		frappe.db.set_value("Item", "_Test Item", "over_delivery_receipt_allowance", 50)

		pr = create_pr_against_po(po.name, received_qty=8)
		self.assertEqual(get_ordered_qty(), existing_ordered_qty)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 12)

		pr.cancel()
		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 6)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 4)

	def test_ordered_qty_against_pi_with_update_stock(self):
		existing_ordered_qty = get_ordered_qty()
		po = create_purchase_order()

		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 10)

		frappe.db.set_value("Item", "_Test Item", "over_delivery_receipt_allowance", 50)
		frappe.db.set_value("Item", "_Test Item", "over_billing_allowance", 20)

		pi = make_pi_from_po(po.name)
		pi.update_stock = 1
		pi.items[0].qty = 12
		pi.insert()
		pi.submit()

		self.assertEqual(get_ordered_qty(), existing_ordered_qty)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 12)

		pi.cancel()
		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 10)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 0)

		frappe.db.set_value("Item", "_Test Item", "over_delivery_receipt_allowance", 0)
		frappe.db.set_value("Item", "_Test Item", "over_billing_allowance", 0)
		frappe.db.set_single_value("Accounts Settings", "over_billing_allowance", 0)

	@change_settings("Buying Settings", {"maintain_same_rate": 0})
	@change_settings("Stock Settings", {"no_partial_indent": 0})
	def test_update_child_qty_rate(self):
		mr = make_material_request(qty=10)
		po = make_purchase_order(mr.name)
		po.supplier = "_Test Supplier"
		po.items[0].qty = 4
		po.save()
		po.submit()

		create_pr_against_po(po.name)

		make_pi_from_po(po.name)

		existing_ordered_qty = get_ordered_qty()
		existing_requested_qty = get_requested_qty()

		trans_item = json.dumps([{"item_code": "_Test Item", "rate": 200, "qty": 7, "docname": po.items[0].name}])
		update_child_items("Purchase Order", po.name, trans_item)

		mr.reload()
		self.assertEqual(mr.items[0].ordered_qty, 7)
		self.assertEqual(mr.per_ordered, 70)
		self.assertEqual(get_requested_qty(), existing_requested_qty - 3)

		po.reload()
		self.assertEqual(po.get("items")[0].rate, 200)
		self.assertEqual(po.get("items")[0].qty, 7)
		self.assertEqual(po.get("items")[0].amount, 1400)
		self.assertEqual(get_ordered_qty(), existing_ordered_qty + 3)

	def test_add_new_item_in_update_child_qty_rate(self):
		po = create_purchase_order(do_not_save=1)
		po.items[0].qty = 4
		po.save()
		po.submit()
		make_pr_against_po(po.name, 2)

		po.load_from_db()
		first_item_of_po = po.get("items")[0]

		trans_item = json.dumps([
			{
				"item_code": first_item_of_po.item_code,
				"rate": first_item_of_po.rate,
				"qty": first_item_of_po.qty,
				"docname": first_item_of_po.name,
			},
			{"item_code": "_Test Item", "rate": 200, "qty": 7},
		])
		update_child_items("Purchase Order", po.name, trans_item)

		po.reload()
		self.assertEqual(len(po.get("items")), 2)
		self.assertEqual(po.status, "To Receive and Bill")

	def test_remove_item_in_update_child_qty_rate(self):
		po = create_purchase_order(do_not_save=1)
		po.items[0].qty = 4
		po.save()
		po.submit()
		make_pr_against_po(po.name, 2)

		po.reload()
		first_item_of_po = po.get("items")[0]
		# add an item
		trans_item = json.dumps([
			{
				"item_code": first_item_of_po.item_code,
				"rate": first_item_of_po.rate,
				"qty": first_item_of_po.qty,
				"docname": first_item_of_po.name,
			},
			{"item_code": "_Test Item", "rate": 200, "qty": 7}])
		update_child_items("Purchase Order", po.name, trans_item)

		po.reload()
		# check if can remove received item
		trans_item = json.dumps([{"item_code": "_Test Item", "rate": 200, "qty": 7, "docname": po.get("items")[1].name}])
		self.assertRaises(frappe.ValidationError, update_child_items, "Purchase Order", po.name, trans_item)

		first_item_of_po = po.get("items")[0]
		trans_item = json.dumps([
			{
				"item_code": first_item_of_po.item_code,
				"rate": first_item_of_po.rate,
				"qty": first_item_of_po.qty,
				"docname": first_item_of_po.name,
			},
		])
		update_child_items("Purchase Order", po.name, trans_item)

		po.reload()
		self.assertEqual(len(po.get("items")), 1)
		self.assertEqual(po.status, "To Receive and Bill")

	def test_update_child_qty_rate_perm(self):
		po = create_purchase_order(item_code="_Test Item", qty=4)

		user = "test@example.com"
		test_user = frappe.get_doc("User", user)
		# a role that can read but not edit Purchase Orders
		test_user.remove_roles("Purchase User", "Purchase Manager", "Accounts User")
		test_user.add_roles("Stock User")
		frappe.set_user(user)
		# Switch back even if an assertion fails, or the following tests run as this user
		self.addCleanup(frappe.set_user, "Administrator")

		# update qty
		trans_item = json.dumps([{"item_code": "_Test Item", "rate": 200, "qty": 7, "docname": po.items[0].name}])
		self.assertRaises(frappe.PermissionError, update_child_items, "Purchase Order", po.name, trans_item)

		# add new item
		trans_item = json.dumps([{"item_code": "_Test Item", "rate": 100, "qty": 2}])
		self.assertRaises(frappe.PermissionError, update_child_items, "Purchase Order", po.name, trans_item)
		frappe.set_user("Administrator")

	def test_update_qty(self):
		po = create_purchase_order()

		pr = make_pr_against_po(po.name, 2)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 2)

		# Check received_qty after making PI from PR without update_stock checked
		pi1 = make_pi_from_pr(pr.name)
		pi1.get("items")[0].qty = 2
		pi1.insert()
		pi1.submit()

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 2)

		# Check received_qty after making PI from PO with update_stock checked
		pi2 = make_pi_from_po(po.name)
		pi2.set("update_stock", 1)
		pi2.get("items")[0].qty = 3
		pi2.insert()
		pi2.submit()

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 5)

		# Check received_qty after making PR from PO
		pr = make_pr_against_po(po.name, 1)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 6)

	def test_return_against_purchase_order(self):
		po = create_purchase_order()

		pr = make_pr_against_po(po.name, 6)

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 6)

		pi2 = make_pi_from_po(po.name)
		pi2.set("update_stock", 1)
		pi2.get("items")[0].qty = 3
		pi2.insert()
		pi2.submit()

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 9)

		# Make return purchase receipt, purchase invoice and check quantity
		from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import (
			make_purchase_invoice as make_purchase_invoice_return,
		)
		from erpnext.stock.doctype.purchase_receipt.test_purchase_receipt import (
			make_purchase_receipt as make_purchase_receipt_return,
		)

		# only returns that reopen the order take the received qty back
		pr1 = make_purchase_receipt_return(is_return=1, return_against=pr.name, qty=-3, do_not_submit=True)
		pr1.reopen_order = 1
		pr1.items[0].purchase_order = po.name
		pr1.items[0].purchase_order_item = po.items[0].name
		pr1.submit()

		pi1 = make_purchase_invoice_return(is_return=1, return_against=pi2.name, qty=-1, update_stock=1, do_not_submit=True)
		pi1.reopen_order = 1
		pi1.items[0].purchase_order = po.name
		pi1.items[0].purchase_order_item = po.items[0].name
		pi1.submit()

		po.load_from_db()
		self.assertEqual(po.get("items")[0].received_qty, 5)

	def test_make_purchase_invoice(self):
		po = create_purchase_order(do_not_submit=True)

		self.assertRaises(frappe.ValidationError, make_pi_from_po, po.name)

		po.submit()
		pi = make_pi_from_po(po.name)

		self.assertEqual(pi.doctype, "Purchase Invoice")
		self.assertEqual(len(pi.get("items", [])), 1)

	def test_purchase_order_on_hold(self):
		po = create_purchase_order(item_code="_Test Product Bundle Item")
		po.db_set("Status", "On Hold")
		pi = make_pi_from_po(po.name)
		pr = make_purchase_receipt(po.name)
		self.assertRaises(frappe.ValidationError, pr.submit)
		self.assertRaises(frappe.ValidationError, pi.submit)

	def test_make_purchase_invoice_with_terms(self):
		po = create_purchase_order(do_not_save=True)

		self.assertRaises(frappe.ValidationError, make_pi_from_po, po.name)

		po.update(
			{"payment_terms_template": "_Test Payment Term Template"},
		)

		po.save()
		po.submit()

		self.assertEqual(po.payment_schedule[0].payment_amount, 2500.0)
		self.assertEqual(getdate(po.payment_schedule[0].due_date), getdate(po.transaction_date))
		self.assertEqual(po.payment_schedule[1].payment_amount, 2500.0)
		self.assertEqual(getdate(po.payment_schedule[1].due_date), add_days(getdate(po.transaction_date), 30))
		pi = make_pi_from_po(po.name)
		pi.save()

		self.assertEqual(pi.doctype, "Purchase Invoice")
		self.assertEqual(len(pi.get("items", [])), 1)

		self.assertEqual(pi.payment_schedule[0].payment_amount, 2500.0)
		self.assertEqual(getdate(pi.payment_schedule[0].due_date), getdate(po.transaction_date))
		self.assertEqual(pi.payment_schedule[1].payment_amount, 2500.0)
		self.assertEqual(getdate(pi.payment_schedule[1].due_date), add_days(getdate(po.transaction_date), 30))

	def test_subcontracting(self):
		po = create_purchase_order(item_code="_Test FG Item", is_subcontracted=1)
		self.assertEqual(len(po.get("supplied_items")), 2)

	def test_warehouse_company_validation(self):
		from erpnext.stock.utils import InvalidWarehouseCompany
		po = create_purchase_order(company="_Test Company 1", do_not_save=True)
		self.assertRaises(InvalidWarehouseCompany, po.insert)

	def test_uom_integer_validation(self):
		from erpnext.utilities.transaction_base import UOMMustBeIntegerError
		po = create_purchase_order(qty=3.4, do_not_save=True)
		self.assertRaises(UOMMustBeIntegerError, po.insert)

	def test_ordered_qty_for_closing_po(self):
		bin = frappe.get_all("Bin", filters={"item_code": "_Test Item", "warehouse": "_Test Warehouse - _TC"},
			fields=["ordered_qty"])

		existing_ordered_qty = bin[0].ordered_qty if bin else 0.0

		po = create_purchase_order(item_code="_Test Item", qty=1)

		self.assertEqual(get_ordered_qty(item_code="_Test Item", warehouse="_Test Warehouse - _TC"), existing_ordered_qty + 1)

		po.update_status("Closed")

		self.assertEqual(get_ordered_qty(item_code="_Test Item", warehouse="_Test Warehouse - _TC"), existing_ordered_qty)

	def test_group_same_items(self):
		frappe.db.set_single_value("Buying Settings", "allow_multiple_items", 1)
		frappe.get_doc({
			"doctype": "Purchase Order",
			"company": "_Test Company",
			"supplier": "_Test Supplier",
			"is_subcontracted": 0,
			"schedule_date": add_days(nowdate(), 1),
			"currency": frappe.get_cached_value("Company", "_Test Company", "default_currency"),
			"conversion_factor": 1,
			"items": get_same_items(),
			"group_same_items": 1,
			}).insert(ignore_permissions=True)

	def test_make_po_without_terms(self):
		po = create_purchase_order(do_not_save=1)

		self.assertFalse(po.get("payment_schedule"))

		po.insert()

		self.assertTrue(po.get("payment_schedule"))

	def test_po_for_blocked_supplier_all(self):
		supplier = frappe.get_doc("Supplier", "_Test Supplier")
		supplier.on_hold = 1
		supplier.save()

		self.assertEqual(supplier.hold_type, "All")
		self.assertRaises(frappe.ValidationError, create_purchase_order)

		supplier.on_hold = 0
		supplier.save()

	def test_po_for_blocked_supplier_invoices(self):
		supplier = frappe.get_doc("Supplier", "_Test Supplier")
		supplier.on_hold = 1
		supplier.hold_type = "Invoices"
		supplier.save()

		self.assertRaises(frappe.ValidationError, create_purchase_order)

		supplier.on_hold = 0
		supplier.save()

	def test_po_for_blocked_supplier_payments(self):
		supplier = frappe.get_doc("Supplier", "_Test Supplier")
		supplier.on_hold = 1
		supplier.hold_type = "Payments"
		supplier.save()

		po = create_purchase_order()

		self.assertRaises(
			frappe.ValidationError, get_payment_entry, dt="Purchase Order", dn=po.name, bank_account="_Test Bank - _TC")

		supplier.on_hold = 0
		supplier.save()

	def test_po_for_blocked_supplier_payments_with_today_date(self):
		supplier = frappe.get_doc("Supplier", "_Test Supplier")
		supplier.on_hold = 1
		supplier.release_date = nowdate()
		supplier.hold_type = "Payments"
		supplier.save()

		po = create_purchase_order()

		self.assertRaises(
			frappe.ValidationError, get_payment_entry, dt="Purchase Order", dn=po.name, bank_account="_Test Bank - _TC")

		supplier.on_hold = 0
		supplier.save()

	def test_po_for_blocked_supplier_payments_past_date(self):
		# this test is meant to fail only if something fails in the try block
		with self.assertRaises(Exception):
			try:
				supplier = frappe.get_doc("Supplier", "_Test Supplier")
				supplier.on_hold = 1
				supplier.hold_type = "Payments"
				supplier.release_date = "2018-03-01"
				supplier.save()

				po = create_purchase_order()
				get_payment_entry("Purchase Order", po.name, bank_account="_Test Bank - _TC")

				supplier.on_hold = 0
				supplier.save()
			except Exception:
				pass
			else:
				raise Exception

	def test_terms_does_not_copy(self):
		po = create_purchase_order()

		self.assertTrue(po.get("payment_schedule"))

		pi = make_pi_from_po(po.name)

		self.assertFalse(pi.get("payment_schedule"))

	def test_terms_copied(self):
		po = create_purchase_order(do_not_save=1)
		po.payment_terms_template = "_Test Payment Term Template"
		po.insert()
		po.submit()
		self.assertTrue(po.get("payment_schedule"))

		pi = make_pi_from_po(po.name)
		pi.insert()
		self.assertTrue(pi.get("payment_schedule"))

	def test_exploded_items_in_subcontracted(self):
		item_code = "_Test Subcontracted FG Item 1"
		make_subcontracted_item(item_code=item_code)

		po = create_purchase_order(item_code=item_code, qty=1,
			is_subcontracted=1, supplier_warehouse="_Test Warehouse 1 - _TC")

		name = frappe.db.get_value("BOM", {"item": item_code}, "name")
		bom = frappe.get_doc("BOM", name)

		exploded_items = sorted([d.item_code for d in bom.exploded_items])
		supplied_items = sorted([d.rm_item_code for d in po.supplied_items])
		self.assertEqual(exploded_items, supplied_items)

		po1 = create_purchase_order(item_code=item_code, qty=1,
			is_subcontracted=1, supplier_warehouse="_Test Warehouse 1 - _TC", include_exploded_items=0)

		supplied_items1 = sorted([d.rm_item_code for d in po1.supplied_items])
		bom_items = sorted([d.item_code for d in bom.items])

		self.assertEqual(supplied_items1, bom_items)

	def test_advance_payment_entry_unlink_against_purchase_order(self):
		from erpnext.accounts.doctype.payment_entry.test_payment_entry import get_payment_entry
		frappe.db.set_value("Accounts Settings", "Accounts Settings",
			"unlink_advance_payment_on_cancelation_of_order", 1)

		po_doc = create_purchase_order()

		pe = get_payment_entry("Purchase Order", po_doc.name, bank_account="_Test Bank - _TC")
		pe.reference_no = "1"
		pe.reference_date = nowdate()
		pe.paid_from_account_currency = po_doc.currency
		pe.paid_to_account_currency = po_doc.currency
		pe.source_exchange_rate = 1
		pe.target_exchange_rate = 1
		pe.paid_amount = po_doc.grand_total
		pe.save(ignore_permissions=True)
		pe.submit()

		po_doc = frappe.get_doc("Purchase Order", po_doc.name)
		po_doc.cancel()

		pe_doc = frappe.get_doc("Payment Entry", pe.name)
		pe_doc.cancel()

		frappe.db.set_value("Accounts Settings", "Accounts Settings",
			"unlink_advance_payment_on_cancelation_of_order", 0)

	def test_schedule_date(self):
		po = create_purchase_order(do_not_submit=True)
		po.schedule_date = None
		po.append("items", {
			"item_code": "_Test Item",
			"qty": 1,
			"rate": 100,
			"schedule_date": add_days(nowdate(), 5),
		})
		po.save()
		self.assertEqual(getdate(po.schedule_date), getdate(add_days(nowdate(), 1)))

		po.items[0].schedule_date = add_days(nowdate(), 2)
		po.save()
		self.assertEqual(getdate(po.schedule_date), getdate(add_days(nowdate(), 2)))


def make_pr_against_po(po, received_qty=0):
	pr = make_purchase_receipt(po)
	pr.get("items")[0].qty = received_qty or 5
	pr.get("items")[0].received_qty = pr.get("items")[0].qty
	pr.insert()
	pr.submit()
	return pr


def make_subcontracted_item(**args):
	from erpnext.manufacturing.doctype.production_plan.test_production_plan import make_bom

	args = frappe._dict(args)

	if not frappe.db.exists("Item", args.item_code):
		make_item(args.item_code, {
			"is_stock_item": 1,
			"is_sub_contracted_item": 1,
			"has_batch_no": args.get("has_batch_no") or 0,
		})

	if not args.raw_materials:
		if not frappe.db.exists("Item", "Test Extra Item 1"):
			make_item("Test Extra Item 1", {
				"is_stock_item": 1,
			})

		if not frappe.db.exists("Item", "Test Extra Item 2"):
			make_item("Test Extra Item 2", {
				"is_stock_item": 1,
			})

		args.raw_materials = ["_Test FG Item", "Test Extra Item 1"]

	if not frappe.db.get_value("BOM", {"item": args.item_code}, "name"):
		make_bom(item=args.item_code, raw_materials=args.get("raw_materials"))


def get_same_items():
	return [
		{
			"item_code": "_Test FG Item",
			"warehouse": "_Test Warehouse - _TC",
			"qty": 1,
			"rate": 500,
			"schedule_date": add_days(nowdate(), 1),
		},
		{
			"item_code": "_Test FG Item",
			"warehouse": "_Test Warehouse - _TC",
			"qty": 4,
			"rate": 500,
			"schedule_date": add_days(nowdate(), 1),
		},
	]


def create_purchase_order(**args):
	po = frappe.new_doc("Purchase Order")
	args = frappe._dict(args)
	if args.transaction_date:
		po.transaction_date = args.transaction_date

	po.schedule_date = add_days(nowdate(), 1)
	po.company = args.company or "_Test Company"
	po.supplier = args.customer or "_Test Supplier"
	po.is_subcontracted = args.is_subcontracted or 0
	po.currency = args.currency or frappe.get_cached_value("Company", po.company, "default_currency")
	po.conversion_factor = args.conversion_factor or 1
	# Subcontracted orders need a supplier warehouse before submit
	po.supplier_warehouse = args.supplier_warehouse or ("_Test Warehouse 1 - _TC" if po.is_subcontracted else None)

	po.append("items", {
		"item_code": args.item or args.item_code or "_Test Item",
		"warehouse": args.warehouse or "_Test Warehouse - _TC",
		"qty": args.qty or 10,
		"rate": args.rate or 500,
		"schedule_date": add_days(nowdate(), 1),
		"include_exploded_items": args.get("include_exploded_items", 1),
	})
	if not args.do_not_save:
		po.insert()
		if not args.do_not_submit:
			if po.is_subcontracted:
				supp_items = po.get("supplied_items")
				for d in supp_items:
					d.reserve_warehouse = args.warehouse or "_Test Warehouse - _TC"
			po.submit()

	return po


def create_pr_against_po(po, received_qty=4):
	pr = make_purchase_receipt(po)
	# Received qty that isn't accepted counts as rejected
	pr.get("items")[0].qty = received_qty
	pr.get("items")[0].received_qty = received_qty
	pr.insert()
	pr.submit()
	return pr


def get_ordered_qty(item_code="_Test Item", warehouse="_Test Warehouse - _TC"):
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse},
		"ordered_qty"))


def get_requested_qty(item_code="_Test Item", warehouse="_Test Warehouse - _TC"):
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse},
		"indented_qty"))


test_dependencies = ["BOM", "Item Price"]

test_records = frappe.get_test_records("Purchase Order")
