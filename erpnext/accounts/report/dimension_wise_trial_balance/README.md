# Dimension-Wise Trial Balance Report

This report provides a dimension-wise view of the trial balance, allowing you to analyze account balances broken down by various dimensions such as Cost Center, Project, Vehicle Workshop Division, Vehicle Brand, Vehicle, Item Group, Customer Group, and Branch.

## Features

- **Standard Trial Balance**: When no grouping is selected, displays the standard trial balance format
- **Dimension-Wise Analysis**: When a grouping dimension is selected, shows separate columns for each dimension value
- **Opening, Movement, and Closing Balances**: For each dimension, displays:
  - Opening Debit/Credit
  - Movement Debit/Credit (period transactions)
  - Closing Debit/Credit

## How to Use

1. Navigate to **Accounts > Reports > Dimension-Wise Trial Balance**
2. Select your **Company** and **Fiscal Year**
3. Set the **From Date** and **To Date** for the period you want to analyze
4. Choose a **Group By** option from the dropdown:
   - Group by Cost Center
   - Group by Project
   - Group by Vehicle Workshop Division
   - Group by Vehicle Brand
   - Group by Vehicle
   - Group by Item Group
   - Group by Customer Group
   - Group by Branch
5. Apply additional filters as needed (Cost Center, Project, Finance Book, etc.)
6. Click **Run** to generate the report

## Report Output

### Standard Trial Balance (No Grouping)
When no grouping is selected, the report shows:
- Account
- Opening (Dr/Cr)
- Debit/Credit (movement)
- Closing (Dr/Cr)

### Dimension-Wise Trial Balance (With Grouping)
When a grouping dimension is selected, the report shows:
- Account
- For each dimension value (e.g., AutoWorks, AutoCare):
  - Opening (Dr) - [Dimension Name]
  - Opening (Cr) - [Dimension Name]
  - Movement (Dr) - [Dimension Name]
  - Movement (Cr) - [Dimension Name]
  - Closing (Dr) - [Dimension Name]
  - Closing (Cr) - [Dimension Name]

## Example Output

If you select "Group by Cost Center" and have two cost centers (AutoWorks and AutoCare), the report will show:

| Account | Opening (Dr) - AutoWorks | Opening (Cr) - AutoWorks | Movement (Dr) - AutoWorks | Movement (Cr) - AutoWorks | Closing (Dr) - AutoWorks | Closing (Cr) - AutoWorks | Opening (Dr) - AutoCare | Opening (Cr) - AutoCare | Movement (Dr) - AutoCare | Movement (Cr) - AutoCare | Closing (Dr) - AutoCare | Closing (Cr) - AutoCare |
|---------|-------------------------|-------------------------|---------------------------|---------------------------|-------------------------|-------------------------|------------------------|------------------------|--------------------------|--------------------------|------------------------|------------------------|
| Cash | 1000.00 | 0.00 | 500.00 | 0.00 | 1500.00 | 0.00 | 2000.00 | 0.00 | 300.00 | 0.00 | 2300.00 | 0.00 |

## Notes

- **Debit is positive, Credit is negative** as per standard accounting principles
- The report automatically refreshes when you change the Group By selection
- Group accounts (parent accounts) will show zero values for dimension-wise columns
- Only leaf accounts (child accounts) will show actual dimension-wise values
- The report respects all standard trial balance filters and settings 