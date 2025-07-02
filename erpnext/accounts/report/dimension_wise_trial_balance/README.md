# Dimension-Wise Trial Balance Report

This report provides a comprehensive dimension-wise view of the trial balance, allowing you to analyze account balances broken down by various dimensions such as Cost Center, Project, and custom accounting dimensions. The report offers enhanced functionality with improved data handling and user-friendly display options.

## Features

- **Dimension-Wise Analysis**: Shows separate columns for each dimension value based on the selected dimension
- **Opening, Movement, and Closing Balances**: For each dimension, displays:
  - Opening Balance (calculated as Opening Debit - Opening Credit)
  - Movement Balance (period transactions as Debit - Credit)
  - Closing Balance (Opening + Movement)
- **Enhanced Cost Center Support**: Uses cost center names instead of IDs for better readability
- **Active Dimension Filtering**: Automatically excludes disabled cost centers and inactive dimensions
- **Hierarchical Account Structure**: Maintains parent-child account relationships with proper value accumulation
- **Default Cost Center Analysis**: Automatically defaults to Cost Center dimension for immediate analysis

## How to Use

1. Navigate to **Accounts > Reports > Dimension-Wise Trial Balance**
2. Select your **Company** and **Fiscal Year**
3. Set the **From Date** and **To Date** for the period you want to analyze
4. Choose a **Based on** option from the dropdown (defaults to "Cost Center"):
   - Cost Center (displays cost center names)
   - Project
   - Custom Accounting Dimensions (dynamically loaded)
5. Apply additional filters as needed:
   - **Cost Center**: Filter by specific cost center (includes child cost centers)
   - **Project**: Filter by specific project
   - **Finance Book**: Filter by finance book
   - **Period Closing Entry**: Include/exclude period closing entries
   - **Show Zero Values**: Display accounts with zero balances
   - **Show Unclosed Fiscal Year's P&L Balances**: Include P&L opening balances
   - **Include Default Book Entries**: Include default finance book entries
6. Click **Run** to generate the report

## Report Output

### Dimension-Wise Trial Balance
The report always shows dimension-wise analysis based on the selected "Based on" field:
- Account
- For each dimension value (e.g., "AutoCare", "AutoWorks"):
  - Opening [Dimension Name]
  - Movement [Dimension Name]
  - Closing [Dimension Name]

## Example Output

If you select "Based on Cost Center" (default) and have two cost centers (AutoCare and AutoWorks), the report will show:

| Account | Opening AutoCare | Opening AutoWorks | Movement AutoCare | Movement AutoWorks | Closing AutoCare | Closing AutoWorks |
|---------|------------------|-------------------|-------------------|-------------------|------------------|-------------------|
| Cash | 1000.00 | 2000.00 | 500.00 | 300.00 | 1500.00 | 2300.00 |
| Accounts Receivable | 5000.00 | 3000.00 | 2000.00 | 1500.00 | 7000.00 | 4500.00 |

## Key Improvements

### 1. **Enhanced Cost Center Handling**
- **Display Names**: Uses `cost_center_name` instead of internal IDs for better readability
- **Active Filtering**: Automatically excludes disabled cost centers
- **Hierarchical Support**: Properly handles cost center hierarchies with lft/rgt structure
- **Default Selection**: Automatically defaults to Cost Center for immediate analysis

### 2. **Improved Data Processing**
- **Single Query Optimization**: Uses optimized SQL queries for better performance
- **Null Safety**: Enhanced error handling and null value management
- **Memory Efficiency**: Improved data structure handling for large datasets

### 3. **Better User Experience**
- **"Based on" Terminology**: More intuitive filter naming
- **Dynamic Dimension Loading**: Automatically loads available accounting dimensions
- **Consistent Labeling**: Uses proper dimension names in column headers
- **Required Field**: "Based on" is a required field ensuring consistent report structure

### 4. **Data Integrity**
- **Active Dimension Filtering**: Only includes active/valid dimensions
- **Proper Joins**: Uses INNER JOINs to exclude invalid data
- **Accurate Calculations**: Proper opening, movement, and closing balance calculations

## Technical Details

### SQL Optimization
The report uses optimized SQL queries with:
- Single comprehensive query for all GL data
- Proper JOINs with dimension tables
- Efficient filtering and grouping
- Memory-conscious data processing

### Dimension Handling
- **Cost Centers**: Uses `cost_center_name` for display, `name` for internal processing
- **Projects**: Direct field mapping
- **Custom Dimensions**: Dynamic field mapping based on accounting dimension configuration

### Data Flow
1. **GL Data Retrieval**: Single optimized query with proper joins
2. **Data Processing**: Structured processing with dimension labels and values
3. **Account Aggregation**: Parent-child account value accumulation
4. **Report Generation**: Final data preparation with proper formatting

## Notes

- **Balance Calculation**: Opening = Opening Debit - Opening Credit, Movement = Period Debit - Period Credit, Closing = Opening + Movement
- **Parent Accounts**: Group accounts show zero values for dimension-wise columns while maintaining structure
- **Leaf Accounts**: Only child accounts show actual dimension-wise values
- **Disabled Dimensions**: Inactive cost centers and disabled dimensions are automatically excluded
- **Performance**: Optimized for large datasets with efficient query patterns
- **Compatibility**: Works with all standard ERPNext accounting configurations
- **Default Behavior**: Always defaults to Cost Center analysis for immediate usability

## Troubleshooting

### Common Issues
1. **No Data Displayed**: Check if the selected dimension has active values
2. **Missing Cost Centers**: Ensure cost centers are not disabled
3. **Incorrect Balances**: Verify fiscal year and date range settings
4. **Performance Issues**: Consider filtering by specific cost centers or projects for large datasets

### Best Practices
1. **Use Specific Filters**: Apply cost center or project filters to improve performance
2. **Check Date Ranges**: Ensure dates are within the fiscal year
3. **Verify Dimensions**: Confirm that accounting dimensions are properly configured
4. **Review Settings**: Check company settings for finance book and cost center configurations 