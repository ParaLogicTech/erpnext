
import frappe

def execute():
    # Fixed asset rows with CWIP enabled are posted to Asset Received But Not Billed,
    # but the row kept the user-selected account. Align the row with the GL.
    frappe.db.sql("""
        update `tabPurchase Invoice Item` pii
        inner join `tabPurchase Invoice` pi on pi.name = pii.parent
        inner join `tabCompany` c on c.name = pi.company
        set pii.expense_account = c.asset_received_but_not_billed
        where pi.docstatus = 1
            and pii.is_fixed_asset = 1
            and ifnull(c.asset_received_but_not_billed, '') != ''
            and ifnull(pii.expense_account, '') != c.asset_received_but_not_billed
            and not exists(select 1 from `tabGL Entry` gle
                where gle.voucher_type = 'Purchase Invoice' and gle.voucher_no = pi.name
                    and gle.account = pii.expense_account)
            and exists(select 1 from `tabGL Entry` gle
                where gle.voucher_type = 'Purchase Invoice' and gle.voucher_no = pi.name
                    and gle.account = c.asset_received_but_not_billed)
    """)
