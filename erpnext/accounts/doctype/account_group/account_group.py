from frappe.model.document import Document
import frappe

class AccountGroup(Document):

    def validate(self):
        self.validate_root_level()
        self.validate_rows()

    def validate_root_level(self):
        """Validate root level account group type."""
        if self.is_root_level:
            if self.reporting_type not in ['Profit and Loss', 'Balance Sheet']:
                frappe.throw('Root level account groups must be either Profit and Loss or Balance Sheet type')
            
            # Check if another root level group exists for this reporting type
            existing_root = frappe.db.get_value('Account Group', 
                {
                    'company': self.company,
                    'is_root_level': 1,
                    'reporting_type': self.reporting_type,
                    'name': ['!=', self.name] 
                }, 
                ['name', 'group_name'],
                as_dict=1
            )
            
            if existing_root:
                frappe.throw(
                    f'Another root level group "{existing_root.group_name}" already exists for {self.reporting_type} reporting type. '
                    f'<a href="/app/account-group/{existing_root.name}">Click here to view</a>'
                )

    def validate_rows(self):
        """Validate rows for duplicates and clear irrelevant fields."""
        seen_accounts = set()
        seen_groups = set()
        
        for i, row in enumerate(self.rows, 1):
            if row.row_type == 'Account':
                # Clear irrelevant fields
                row.account_group = None
                row.section_name = None
                row.section_account_groups = None
                
                # Check for duplicates
                if row.account in seen_accounts:
                    frappe.throw(f'Row {i}: Account {row.account} appears multiple times')
                seen_accounts.add(row.account)
                
                
            elif row.row_type == 'Account Group':
                # Clear irrelevant fields
                row.account = None
                row.section_name = None
                row.section_account_groups = None
                
                
                # Check for duplicates
                if row.account_group in seen_groups:
                    frappe.throw(f'Row {i}: Account Group {row.account_group} appears multiple times')
                seen_groups.add(row.account_group)
                
            elif row.row_type in ('Section Break', 'Section Group'):
                # Clear irrelevant fields
                row.account = None
                row.account_group = None