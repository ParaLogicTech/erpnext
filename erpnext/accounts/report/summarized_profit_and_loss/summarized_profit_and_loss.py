# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, get_first_day, add_years
from datetime import timedelta
from erpnext.accounts.doctype.budget.budget import get_accumulated_monthly_budget


def execute(filters=None):
    return SummarizedProfitAndLossReport(filters).run()


class SummarizedProfitAndLossReport:
    def __init__(self, filters=None):
        self.filters = frappe._dict(filters or {})

    def run(self):
        return self.get_columns(), self.get_data()

    def get_columns(self):
        return [
            {
                "fieldname": "row_type",
                "label": _("Type"),
                "fieldtype": "Data",
                "hidden": 1,
                "width": 0
            },
            {
                "fieldname": "account_name",
                "label": _("Account"),
                "fieldtype": "Data",
                "width": 300
            },
            {
                "fieldname": "mtd_actual",
                "label": _("MTD Actual"),
                "fieldtype": "Currency",
                "width": 150
            },
            {
                "fieldname": "mtd_budget",
                "label": _("MTD Budget"),
                "fieldtype": "Currency",
                "width": 150
            },
            {
                "fieldname": "mtd_prev_year",
                "label": _("MTD Previous Year"),
                "fieldtype": "Currency",
                "width": 150
            },
            {
                "fieldname": "ytd_actual",
                "label": _("YTD Actual"),
                "fieldtype": "Currency",
                "width": 150
            },
            {
                "fieldname": "ytd_budget",
                "label": _("YTD Budget"),
                "fieldtype": "Currency",
                "width": 150
            },
            {
                "fieldname": "ytd_prev_year",
                "label": _("YTD Previous Year"),
                "fieldtype": "Currency",
                "width": 150
            }
        ]

    def get_data(self):
        report_date = getdate(self.filters.get('report_date'))
        month_start_date = get_first_day(report_date)
        year_start_date = getdate(f"{report_date.year}-01-01")
        
        dates = {
            'report_date': report_date,
            'month_start': month_start_date,
            'year_start': year_start_date,
            'prev_year_date': add_years(report_date, -1),
            'prev_year_month_start': add_years(month_start_date, -1),
            'prev_year_start': add_years(year_start_date, -1)
        }

        if self.filters.get('account_group'):
            data = self.get_account_group_data(
                self.filters.get('account_group'),
                self.filters.get('company'),
                **dates
            )
            
            # Add total row when filtered
            totals = {
                'mtd_actual': 0, 'mtd_budget': 0, 'mtd_prev_year': 0,
                'ytd_actual': 0, 'ytd_budget': 0, 'ytd_prev_year': 0
            }
            
            for row in data:
                if row.get('row_type') in ['Account', 'Account Group']:
                    for key in totals:
                        totals[key] += row.get(key, 0)
            
            data.append({
                'row_type': 'Total',
                'account_name': 'Total',
                'is_bold': 1,
                **totals
            })
            
            return data

        root_group = frappe.get_value(
            "Account Group",
            {
                "company": self.filters.get('company'),
                "is_root_level": 1,
                "reporting_type": "Profit and Loss"
            },
            ["name", "group_name"]
        )

        if not root_group:
            frappe.msgprint("No root level Profit and Loss group found for this company. Please create one first.")
            return []

        data = self.get_account_group_data(
            root_group[0],
            self.filters.get('company'),
            **dates
        )

        for row in data:
            if row.get('row_type') == 'Account Group':
                row['account_group'] = row.get('account_group') or row.get('name')

        return data

    def get_account_group_data(self, group_name, company, report_date, month_start, year_start,
                            prev_year_date, prev_year_month_start, prev_year_start):
        data = []
        group = frappe.get_doc("Account Group", group_name)
        running_totals = {k: 0 for k in ['mtd_actual', 'mtd_budget', 'mtd_prev_year', 
                                       'ytd_actual', 'ytd_budget', 'ytd_prev_year']}

        # Preload child group data
        child_groups = {}
        
        for row in group.rows:
            if row.row_type == "Account Group":
                child_group = frappe.get_doc("Account Group", row.account_group)
                
                # Recursively calculate totals for child groups
                child_totals = self.calculate_group_totals(
                    child_group, company, report_date, month_start, year_start,
                    prev_year_date, prev_year_month_start, prev_year_start
                )
                
                child_groups[row.account_group] = {
                    "name": row.account_group,
                    "group_name": child_group.group_name,
                    "totals": child_totals,
                    "category": child_group.category
                }

        for row in group.rows:
            if row.row_type == "Account":
                # Get individual account balances
                account_data = self.get_account_balances(
                    row.account, company, report_date, month_start, year_start,
                    prev_year_date, prev_year_month_start, prev_year_start
                )
                
                data.append(account_data)
                
                for key in running_totals:
                    running_totals[key] += account_data.get(key, 0)

            elif row.row_type == "Account Group":
                # Use preloaded child group data
                child_info = child_groups[row.account_group]
                
                data.append({
                    "row_type": "Account Group",
                    "account_name": child_info["group_name"],
                    "is_bold": 1,
                    "account_group": child_info["name"],
                    **child_info["totals"]
                })
                
                for key in running_totals:
                    running_totals[key] += child_info["totals"][key]

            elif row.row_type == "Section Break":
                running_totals = {key: 0 for key in running_totals}
                
                data.append({
                    "row_type": "Section Break",
                    "account_name": row.section_name or "",
                    "is_bold": 1
                })

            elif row.row_type == "Section Group":
                section_totals = self.calculate_section_totals(row, child_groups, running_totals)
                data.append({
                    "row_type": "Section Group",
                    "account_name": row.section_name,
                    "is_bold": 1,
                    **section_totals
                })
                running_totals = {key: 0 for key in running_totals}

        return data

    def calculate_section_totals(self, row, child_groups, running_totals):
        if not row.section_account_groups:
            return running_totals.copy()

        section_totals = {key: 0 for key in running_totals}
        included_groups = []
        included_categories = set()

        for line in row.section_account_groups.split('\n'):
            if line.strip():
                group_code = line.strip().split('(')[-1].rstrip(')')
                if group_code and group_code in child_groups:
                    group_info = child_groups[group_code]
                    included_groups.append(group_info)
                    included_categories.add(group_info["category"])

        if included_categories == {"Income"} or included_categories == {"Expense"}:
            for group_info in included_groups:
                for key in section_totals:
                    section_totals[key] += group_info["totals"][key]
        else:
            income_totals = {key: 0 for key in running_totals}
            expense_totals = {key: 0 for key in running_totals}

            for group_info in included_groups:
                target_dict = income_totals if group_info["category"] == "Income" else expense_totals
                for key in target_dict:
                    target_dict[key] += group_info["totals"][key]

            for key in section_totals:
                section_totals[key] = income_totals[key] - expense_totals[key]

        return section_totals

    def calculate_group_totals(self, group, company, report_date, month_start, year_start,
                             prev_year_date, prev_year_month_start, prev_year_start):
        totals = {key: 0 for key in ['mtd_actual', 'mtd_budget', 'mtd_prev_year', 
                                    'ytd_actual', 'ytd_budget', 'ytd_prev_year']}
        
        accounts = frappe.db.sql("""
            WITH RECURSIVE cte AS (
                SELECT a.name, a.account_type
                FROM `tabAccount` a
                INNER JOIN `tabAccount Group Row` agr ON agr.account = a.name
                WHERE agr.parent = %s AND agr.row_type = 'Account'
                UNION ALL
                SELECT a.name, a.account_type
                FROM `tabAccount` a
                INNER JOIN `tabAccount Group Row` agr ON agr.account = a.name
                INNER JOIN `tabAccount Group` ag ON agr.parent = ag.name
                INNER JOIN `tabAccount Group Row` pagr ON pagr.account_group = ag.name
                WHERE pagr.parent = %s AND agr.row_type = 'Account'
            )
            SELECT name, account_type FROM cte
        """, (group.name, group.name), as_dict=1)

        # Calculate totals for each account
        for account in accounts:
            account_data = self.get_account_balances(
                account.name, company, report_date, month_start, year_start,
                prev_year_date, prev_year_month_start, prev_year_start
            )
            
            for key in totals:
                totals[key] += account_data.get(key, 0)

        return totals

    def get_account_balances(self, account, company, report_date, month_start, year_start,
                             prev_year_date, prev_year_month_start, prev_year_start):
        account_doc = frappe.get_doc("Account", account)
        fiscal_year = report_date.year

        return {
            "row_type": "Account",
            "account_name": f"{account_doc.account_name} ({account_doc.account_number})",
            "account": account,
            "account_type": account_doc.account_type,
            "mtd_actual": self.get_balance(account, company, month_start, report_date, account_doc),
            "mtd_budget": self.get_budget_amount(account, company, month_start, report_date, year_start, fiscal_year),
            "mtd_prev_year": self.get_balance(account, company, prev_year_month_start, prev_year_date, account_doc),
            "ytd_actual": self.get_balance(account, company, year_start, report_date, account_doc),
            "ytd_budget": self.get_budget_amount(account, company, year_start, report_date, year_start, fiscal_year),
            "ytd_prev_year": self.get_balance(account, company, prev_year_start, prev_year_date, account_doc)
        }

    def get_balance(self, account, company, start_date, end_date, account_doc):
        """Get GL balance for the account between given dates."""
        balance = frappe.db.sql("""
            SELECT SUM(debit) - SUM(credit)
            FROM `tabGL Entry`
            WHERE account=%s AND company=%s
                AND posting_date BETWEEN %s AND %s
                AND docstatus = 1
        """, (account, company, start_date, end_date))[0][0] or 0
        
        multiplier = 1 if account_doc.root_type in ["Asset", "Expense"] else -1
        return balance * multiplier

    def get_budget_amount(self, account, company, start_date, end_date, year_start, fiscal_year):
        """Get budget amount for the account between given dates."""
        # Query budget information
        budget_data = frappe.db.sql("""
            SELECT ba.budget_amount, b.monthly_distribution
            FROM `tabBudget Account` ba
            INNER JOIN `tabBudget` b ON ba.parent = b.name
            WHERE ba.account = %s AND b.company = %s 
                AND b.fiscal_year = %s AND b.docstatus = 1
            LIMIT 1
        """, (account, company, fiscal_year), as_dict=1)
        
        # Set defaults if no budget found
        budget = 0
        monthly_distribution = None
        
        # Extract values if budget exists
        if budget_data:
            budget = budget_data[0].budget_amount or 0
            monthly_distribution = budget_data[0].monthly_distribution

        if monthly_distribution:
            return (get_accumulated_monthly_budget(monthly_distribution, end_date, fiscal_year, budget) -
                   get_accumulated_monthly_budget(monthly_distribution, start_date - timedelta(days=1), fiscal_year, budget)
                   if start_date > year_start else
                   get_accumulated_monthly_budget(monthly_distribution, end_date, fiscal_year, budget))

        fy_start, fy_end = frappe.db.get_value('Fiscal Year', fiscal_year, ['year_start_date', 'year_end_date'])
        days_in_period = (end_date - start_date).days + 1
        days_in_year = (fy_end - fy_start).days + 1 if fy_start and fy_end else 365
        return (budget * days_in_period / days_in_year)


 