from frappe import _


def get_data():
	return {
		'heatmap': True,
		'heatmap_message': _('This is based on the attendance of this Employee'),
		'fieldname': 'employee',
		'non_standard_fieldnames': {
			'Task': 'assigned_to',
		},
		'transactions': [
			{
				'label': _('Leave and Attendance'),
				'items': ['Attendance', 'Attendance Request', 'Leave Application', 'Leave Allocation', 'Employee Checkin']
			},
			{
				'label': _('Payroll'),
				'items': ['Salary Structure Assignment', 'Salary Slip', 'Additional Salary', 'Employee Incentive', 'Retention Bonus']
			},
			{
				'label': _('Lifecycle'),
				'items': ['Employee Transfer', 'Employee Promotion', 'Employee Separation', 'Appraisal']
			},
			{
				'label': _('Training'),
				'items': ['Training Event', 'Training Result', 'Training Feedback', 'Employee Skill Map']
			},
			{
				'label': _('Shift'),
				'items': ['Shift Request', 'Shift Assignment']
			},
			{
				'label': _('Expense'),
				'items': ['Expense Claim', 'Travel Request', 'Employee Advance']
			},
			# {
			# 	'label': _('Benefit'),
			# 	'items': ['Employee Benefit Application', 'Employee Benefit Claim']
			# },
			{
				'label': _('Timesheets'),
				'items': ['Timesheet', 'Task', 'Activity Cost']
			},
		]
	}
