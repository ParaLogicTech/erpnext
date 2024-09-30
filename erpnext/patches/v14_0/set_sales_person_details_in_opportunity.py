import frappe

def execute():
    frappe.reload_doc("crm", "doctype", "opportunity")

    frappe.db.sql("""
        UPDATE `tabOpportunity` AS opp
        INNER JOIN `tabSales Person` AS sp 
            ON sp.name = opp.sales_person
        INNER JOIN `tabEmployee` AS emp 
            ON emp.name = sp.employee
        SET opp.sales_person_contact_no = emp.cell_number, 
            opp.sales_person_email = CASE
                WHEN emp.company_email IS NOT NULL AND emp.company_email != ''
                THEN emp.company_email
                ELSE emp.personal_email
            END
    """)