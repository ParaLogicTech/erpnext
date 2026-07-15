import click
import frappe


def execute():
    click.echo("Updating Quotation Lost Date...")
    frappe.db.sql("""
        UPDATE `tabQuotation`
        SET lost_date = transaction_date
        WHERE status = 'Lost' AND lost_date IS NULL
    """)
