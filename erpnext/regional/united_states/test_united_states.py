# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
import frappe
import unittest


class TestUnitedStates(unittest.TestCase):
    def test_irs_1099_custom_field(self):

        if not frappe.db.exists("Supplier", "_US 1099 Test Supplier"):
            doc = frappe.new_doc("Supplier")
            doc.supplier_name = "_US 1099 Test Supplier"
            doc.supplier_group = "Services"
            doc.supplier_type = "Company"
            doc.country = "United States"
            doc.tax_id = "04-1234567"
            doc.irs_1099 = 1
            doc.save()
            frappe.db.commit()
            supplier = frappe.get_doc('Supplier', "_US 1099 Test Supplier")
            self.assertEqual(supplier.irs_1099, 1)
