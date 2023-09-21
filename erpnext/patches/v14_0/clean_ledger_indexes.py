import frappe


def execute():
	if frappe.db.has_index("tabStock Ledger Entry", "to_rename"):
		frappe.db.sql_ddl(f"ALTER TABLE `tabStock Ledger Entry` DROP INDEX `to_rename`")
	if frappe.db.has_index("tabGL Entry", "to_rename"):
		frappe.db.sql_ddl(f"ALTER TABLE `tabGL Entry` DROP INDEX `to_rename`")

	if frappe.db.has_index("tabGL Entry", "voucher_type_voucher_no_index"):
		frappe.db.sql_ddl(f"ALTER TABLE `tabGL Entry` DROP INDEX `voucher_type_voucher_no_index`")
	if frappe.db.has_index("tabGL Entry", "against_voucher_type_against_voucher_index"):
		frappe.db.sql_ddl(f"ALTER TABLE `tabGL Entry` DROP INDEX `against_voucher_type_against_voucher_index`")

	if frappe.db.has_index("tabStock Ledger Entry", "batch_no_item_code_warehouse_index"):
		frappe.db.sql_ddl(f"ALTER TABLE `tabStock Ledger Entry` DROP INDEX `batch_no_item_code_warehouse_index`")
