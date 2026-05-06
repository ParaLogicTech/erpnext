import frappe

def execute():
    frappe.db.sql("""
        UPDATE `tabProject`
        SET total_cost =
            COALESCE(timesheet_costing_amount, 0)
          + COALESCE(total_expense_claim, 0)
          + COALESCE(total_purchase_cost, 0)
          + COALESCE(total_consumed_material_cost, 0)
          + COALESCE(material_cost_of_sales, 0)
    """)