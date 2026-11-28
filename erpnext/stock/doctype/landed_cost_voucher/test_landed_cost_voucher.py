# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import unittest

import frappe

from erpnext.accounts.doctype.account.test_account import get_inventory_account
from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice
from erpnext.stock.doctype.landed_cost_voucher.landed_cost_voucher import get_landed_cost_voucher
from erpnext.stock.doctype.purchase_receipt.test_purchase_receipt import (
	get_gl_entries,
	make_purchase_receipt,
	set_perpetual_inventory,
)
from erpnext.stock.doctype.purchase_receipt.test_purchase_receipt import test_records as pr_test_records


class TestLandedCostVoucher(unittest.TestCase):
	def test_landed_cost_voucher(self):
		frappe.db.set_single_value("Buying Settings", "allow_multiple_items", 1)

		pr = make_purchase_receipt(company="_Test Company with perpetual inventory", warehouse="Stores - TCP1", supplier_warehouse="Work in Progress - TCP1", get_multiple_items=True, get_taxes_and_charges=True)

		last_sle = frappe.db.get_value("Stock Ledger Entry", {
				"voucher_type": pr.doctype,
				"voucher_no": pr.name,
				"item_code": "_Test Item",
				"warehouse": "Stores - TCP1",
			},
			fieldname=["qty_after_transaction", "stock_value"], as_dict=1)

		submit_landed_cost_voucher("Purchase Receipt", pr.name)

		pr_lc_value = frappe.db.get_value("Purchase Receipt Item", {"parent": pr.name}, "landed_cost_voucher_amount")
		self.assertEqual(pr_lc_value, 25.0)

		last_sle_after_landed_cost = frappe.db.get_value("Stock Ledger Entry", {
				"voucher_type": pr.doctype,
				"voucher_no": pr.name,
				"item_code": "_Test Item",
				"warehouse": "Stores - TCP1",
			},
			fieldname=["qty_after_transaction", "stock_value"], as_dict=1)

		self.assertEqual(last_sle.qty_after_transaction, last_sle_after_landed_cost.qty_after_transaction)

		self.assertEqual(last_sle_after_landed_cost.stock_value - last_sle.stock_value, 25.0)

		gl_entries = get_gl_entries("Purchase Receipt", pr.name)

		self.assertTrue(gl_entries)

		stock_in_hand_account = get_inventory_account(pr.company, pr.get("items")[0].warehouse)
		fixed_asset_account = get_inventory_account(pr.company, pr.get("items")[1].warehouse)

		if stock_in_hand_account == fixed_asset_account:
			expected_values = {
				stock_in_hand_account: [800.0, 0.0],
				"Stock Received But Not Billed - TCP1": [0.0, 750.0],
				"Expenses Included In Valuation - TCP1": [0.0, 50.0],
			}
		else:
			expected_values = {
				stock_in_hand_account: [400.0, 0.0],
				fixed_asset_account: [400.0, 0.0],
				"Stock Received But Not Billed - TCP1": [0.0, 750.0],
				"Expenses Included In Valuation - TCP1": [0.0, 50.0],
			}

		for gle in gl_entries:
			self.assertEqual(expected_values[gle.account][0], gle.debit)
			self.assertEqual(expected_values[gle.account][1], gle.credit)

	def test_landed_cost_voucher_against_purchase_invoice(self):

		pi = make_purchase_invoice(update_stock=1, posting_date=frappe.utils.nowdate(),
			posting_time=frappe.utils.nowtime(), cash_bank_account="Cash - TCP1",
			company="_Test Company with perpetual inventory", supplier_warehouse="Work In Progress - TCP1",
			warehouse="Stores - TCP1", cost_center="Main - TCP1",
			expense_account="_Test Account Cost for Goods Sold - TCP1")

		last_sle = frappe.db.get_value("Stock Ledger Entry", {
				"voucher_type": pi.doctype,
				"voucher_no": pi.name,
				"item_code": "_Test Item",
				"warehouse": "Stores - TCP1",
			},
			fieldname=["qty_after_transaction", "stock_value"], as_dict=1)

		submit_landed_cost_voucher("Purchase Invoice", pi.name)

		pi_lc_value = frappe.db.get_value("Purchase Invoice Item", {"parent": pi.name},
			"landed_cost_voucher_amount")

		self.assertEqual(pi_lc_value, 50.0)

		last_sle_after_landed_cost = frappe.db.get_value("Stock Ledger Entry", {
				"voucher_type": pi.doctype,
				"voucher_no": pi.name,
				"item_code": "_Test Item",
				"warehouse": "Stores - TCP1",
			},
			fieldname=["qty_after_transaction", "stock_value"], as_dict=1)

		self.assertEqual(last_sle.qty_after_transaction, last_sle_after_landed_cost.qty_after_transaction)

		self.assertEqual(last_sle_after_landed_cost.stock_value - last_sle.stock_value, 50.0)

		gl_entries = get_gl_entries("Purchase Invoice", pi.name)

		self.assertTrue(gl_entries)
		stock_in_hand_account = get_inventory_account(pi.company, pi.get("items")[0].warehouse)

		expected_values = {
			stock_in_hand_account: [300.0, 0.0],
			"Creditors - TCP1": [0.0, 250.0],
			"Expenses Included In Valuation - TCP1": [0.0, 50.0],
		}

		for gle in gl_entries:
			self.assertEqual(expected_values[gle.account][0], gle.debit)
			self.assertEqual(expected_values[gle.account][1], gle.credit)

	def test_landed_cost_voucher_for_serialized_item(self):
		serial_nos = [frappe.generate_hash(length=10).upper() for _i in range(5)]
		pr = make_purchase_receipt(company="_Test Company with perpetual inventory", warehouse="Stores - TCP1",
		supplier_warehouse="Work in Progress - TCP1", get_multiple_items=True,
		get_taxes_and_charges=True, do_not_submit=True)

		pr.items[0].item_code = "_Test Serialized Item"
		pr.items[0].serial_no = "\n".join(serial_nos)
		pr.submit()

		serial_no_rate = frappe.db.get_value("Serial No", serial_nos[0], "purchase_rate")

		submit_landed_cost_voucher("Purchase Receipt", pr.name)

		serial_no = frappe.db.get_value("Serial No", serial_nos[0],
			["warehouse", "purchase_rate"], as_dict=1)

		self.assertEqual(serial_no.purchase_rate - serial_no_rate, 5.0)
		self.assertEqual(serial_no.warehouse, "Stores - TCP1")

	def test_landed_cost_voucher_for_odd_numbers(self):

		pr = make_purchase_receipt(company="_Test Company with perpetual inventory", warehouse="Stores - TCP1", supplier_warehouse="Work in Progress - TCP1", do_not_save=True)
		pr.items[0].cost_center = "Main - TCP1"
		for _x in range(2):
			pr.append("items", {
				"item_code": "_Test Item",
				"warehouse": "Stores - TCP1",
				"cost_center": "Main - TCP1",
				"qty": 5,
				"rate": 50,
			})
		pr.submit()

		lcv = submit_landed_cost_voucher("Purchase Receipt", pr.name, 123.22)

		self.assertEqual(lcv.items[0].applicable_charges, 41.07)
		self.assertEqual(lcv.items[2].applicable_charges, 41.08)

	def test_multiple_landed_cost_voucher_against_pr(self):
		pr = make_purchase_receipt(company="_Test Company with perpetual inventory", warehouse="Stores - TCP1",
			supplier_warehouse="Stores - TCP1", do_not_save=True)

		pr.append("items", {
			"item_code": "_Test Item",
			"warehouse": "Stores - TCP1",
			"cost_center": "Main - TCP1",
			"qty": 5,
			"rate": 100,
		})

		pr.submit()

		lcv1 = make_landed_cost_voucher(receipt_document_type="Purchase Receipt",
			receipt_document=pr.name, charges=100, do_not_save=True)

		lcv1.set("items", [
			lcv1.get("items")[0],
		])
		lcv1.insert()
		lcv1.submit()

		lcv2 = make_landed_cost_voucher(receipt_document_type="Purchase Receipt",
			receipt_document=pr.name, charges=100, do_not_save=True)

		lcv2.set("items", [
			lcv2.get("items")[1],
		])
		lcv2.insert()
		lcv2.submit()

		pr.load_from_db()

		self.assertEqual(pr.items[0].landed_cost_voucher_amount, 100)
		self.assertEqual(pr.items[1].landed_cost_voucher_amount, 100)


def make_landed_cost_voucher(**args):
	"""Landed Cost Voucher payable to the receipt's supplier, with items from the receipt, as Make Landed Cost Voucher
	does. Charges are distributed by amount when the voucher is saved."""
	args = frappe._dict(args)
	ref_doc = frappe.get_doc(args.receipt_document_type, args.receipt_document)

	lcv = get_landed_cost_voucher(args.receipt_document_type, args.receipt_document)
	lcv.party_type = "Supplier"
	lcv.party = ref_doc.supplier
	lcv.append("taxes", {
		"remarks": "Shipping Charges",
		"account_head": "Expenses Included In Valuation - TCP1",
		"distribution_criteria": "Amount",
		"amount": args.charges,
	})

	if not args.do_not_save:
		lcv.insert()
		if not args.do_not_submit:
			lcv.submit()

	return lcv


def submit_landed_cost_voucher(receipt_document_type, receipt_document, charges=50):
	return make_landed_cost_voucher(receipt_document_type=receipt_document_type, receipt_document=receipt_document,
		charges=charges)


test_records = frappe.get_test_records("Landed Cost Voucher")
