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
                frappe.throw(_(
                    'Another root level group "{0}" already exists for {1} reporting type. <a href="/app/account-group/{2}">Click here to view</a>'
                ).format(existing_root.group_name, self.reporting_type, existing_root.name))

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
                    frappe.throw(_(
                        'Row {0}: Account {1} appears multiple times'
                    ).format(i, row.account))
                seen_accounts.add(row.account)
                
                
            elif row.row_type == 'Account Group':
                # Clear irrelevant fields
                row.account = None
                row.section_name = None
                row.section_account_groups = None
                
                
                # Check for duplicates
                if row.account_group in seen_groups:
                    frappe.throw(_(
                        'Row {0}: Account Group {1} appears multiple times'
                    ).format(i, row.account_group))
                seen_groups.add(row.account_group)
                
            elif row.row_type in ('Section Break', 'Section Group'):
                # Clear irrelevant fields
                row.account = None
                row.account_group = None