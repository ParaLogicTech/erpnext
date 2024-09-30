frappe.treeview_settings["Sales Person"] = {
	fields: [
		{
			fieldname: 'sales_person_name',
			label:__('Sales Person Name'),
			fieldtype: 'Data',
			reqd: 1
		},
		{
			fieldtype:'Link',
			fieldname:'employee',
			label:__('Employee'),
			options: 'Employee',
			description: __("Please enter Employee ID of this Sales Person")
		},
		{
			fieldtype:'Check',
			fieldname:'is_group',
			label:__('Group Node'),
			description: __("Further nodes can be only created under 'Group' type nodes")
		}
	],
}
