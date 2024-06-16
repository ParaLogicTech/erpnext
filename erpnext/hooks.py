from frappe import _

app_name = "erpnext"
app_title = "ERPNext"
app_publisher = "Frappe Technologies Pvt. Ltd."
app_description = """ERP made simple"""
app_icon = "fa fa-th"
app_color = "#e74c3c"
app_email = "info@erpnext.com"
app_license = "GNU General Public License (v3)"
source_link = "https://github.com/frappe/erpnext"
app_logo_url = '/assets/erpnext/images/erp-icon.svg'
required_apps = ["crm"]


develop_version = '14.x.x-develop'

app_include_js = "erpnext.bundle.js"
app_include_css = "erpnext.bundle.css"

web_include_js = "erpnext-web.bundle.js"
web_include_css = "erpnext-web.bundle.css"

email_css = "email_erpnext.bundle.css"

doctype_js = {
	"Communication": "overrides/communication_hooks.js",
	"Event": "overrides/event_hooks.js",
	"Website Theme": "overrides/website_theme_hooks.js",

	"Sales Person": "overrides/sales_person/sales_person_hooks.js",
	"Territory": "overrides/territory/territory_hooks.js",
	"Lead": "overrides/lead/lead_hooks.js",
	"Opportunity": "overrides/opportunity/opportunity_hooks.js",
	"Appointment Type": "overrides/appointment_type/appointment_type_hooks.js",
	"Appointment": "overrides/appointment/appointment_hooks.js",
	"Customer Feedback": "overrides/customer_feedback/customer_feedback_hooks.js",
}

doctype_list_js = {
	"Appointment": "overrides/appointment/appointment_list_hooks.js",
}

doctype_tree_js = {
	"Sales Person": "overrides/sales_person/sales_person_tree_hooks.js",
}

override_doctype_class = {
	"Sales Person": "erpnext.overrides.sales_person.sales_person_hooks.SalesPersonERP",
	"Territory": "erpnext.overrides.territory.territory_hooks.TerritoryERP",
	"Lead": "erpnext.overrides.lead.lead_hooks.LeadERP",
	"Opportunity": "erpnext.overrides.opportunity.opportunity_hooks.OpportunityERP",
	"Appointment Type": "erpnext.overrides.appointment_type.appointment_type_hooks.AppointmentTypeERP",
	"Appointment": "erpnext.overrides.appointment.appointment_hooks.AppointmentERP",
	"Customer Feedback": "erpnext.overrides.customer_feedback.customer_feedback_hooks.CustomerFeedbackERP",
}

override_doctype_dashboards = {
	"Sales Person": "erpnext.overrides.sales_person.sales_person_hooks.override_sales_person_dashboard",
	"Lead": "erpnext.overrides.lead.lead_hooks.override_lead_dashboard",
	"Appointment": "erpnext.overrides.appointment.appointment_hooks.override_appointment_dashboard",
}

fixtures = [
	{
		"doctype": "Custom Field",
		"filters": {
			"name": ["in", [
				"Sales Person-employee",
				"Sales Person-employee_name",
				"Sales Person-cb_employee",
				"Sales Person-department",
				"Sales Person-designation",
				"Sales Person-sales_commission_category",
				"Sales Person-targets_section",
				"Sales Person-targets",

				"Territory-targets_section",
				"Territory-targets",

				"Campaign-claim_customer",
				"Campaign-claim_customer_name",

				"Lead-customer",

				"Opportunity-company",
				"Opportunity-maintenance_schedule",
				"Opportunity-maintenance_schedule_row",
				"Opportunity-applies_to_variant_of",
				"Opportunity-applies_to_variant_of_name",
				"Opportunity-applies_to_serial_no",
				"Opportunity-applies_to_item",
				"Opportunity-applies_to_item_name",

				"Opportunity Item-item_code",
				"Opportunity Item-uom",
				"Opportunity Item-item_group",
				"Opportunity Item-brand",

				"Appointment Type-company",
				"Appointment Type-holiday_list",

				"Appointment-company",
				"Appointment-applies_to_variant_of",
				"Appointment-applies_to_variant_of_name",
				"Appointment-applies_to_serial_no",
				"Appointment-applies_to_item",
				"Appointment-applies_to_item_name",
				"Appointment-project_template",
				"Appointment-project_template_name",
				"Appointment Type-validate_duplicate_appointment",

				"Customer Feedback-applies_to_variant_of",
				"Customer Feedback-applies_to_variant_of_name",
				"Customer Feedback-applies_to_serial_no",
				"Customer Feedback-applies_to_item",
				"Customer Feedback-applies_to_item_name",
			]]
		}
	},
]

welcome_email = "erpnext.setup.utils.welcome_email"

# setup wizard
setup_wizard_requires = "assets/erpnext/js/setup_wizard.js"
setup_wizard_stages = "erpnext.setup.setup_wizard.setup_wizard.get_setup_stages"
setup_wizard_test = "erpnext.setup.setup_wizard.test_setup_wizard.run_setup_wizard_test"

before_install = "erpnext.setup.install.check_setup_wizard_not_completed"
after_install = "erpnext.setup.install.after_install"

boot_session = "erpnext.startup.boot.boot_session"
notification_config = "erpnext.startup.notifications.get_notification_config"
get_help_messages = "erpnext.utilities.activation.get_help_messages"
get_user_progress_slides = "erpnext.utilities.user_progress.get_user_progress_slides"
update_and_get_user_progress = "erpnext.utilities.user_progress_utils.update_default_domain_actions_and_get_state"
leaderboards = "erpnext.startup.leaderboard.get_leaderboards"


on_session_creation = [
	"erpnext.portal.utils.create_customer_or_supplier",
	"erpnext.shopping_cart.utils.set_cart_count"
]
on_logout = "erpnext.shopping_cart.utils.clear_cart_count"

treeviews = ['Account', 'Cost Center', 'Warehouse', 'Item Group', 'Customer Group', 'Assessment Group', 'Department']

# website
update_website_context = ["erpnext.shopping_cart.utils.update_website_context", "erpnext.education.doctype.education_settings.education_settings.update_website_context"]
my_account_context = "erpnext.shopping_cart.utils.update_my_account_context"

email_append_to = ["Job Applicant", "Issue"]

calendars = ["Task", "Work Order", "Leave Application", "Sales Order", "Holiday List", "Course Schedule"]

domains = {
	'Agriculture': 'erpnext.domains.agriculture',
	'Distribution': 'erpnext.domains.distribution',
	'Education': 'erpnext.domains.education',
	'Healthcare': 'erpnext.domains.healthcare',
	'Hospitality': 'erpnext.domains.hospitality',
	'Manufacturing': 'erpnext.domains.manufacturing',
	'Non Profit': 'erpnext.domains.non_profit',
	'Retail': 'erpnext.domains.retail',
	'Services': 'erpnext.domains.services',
	'Vehicles': 'erpnext.domains.vehicles',
}

website_generators = ["Item Group", "Item", "BOM", "Sales Partner",
	"Job Opening", "Student Admission"]

website_context = {
	"favicon": 	"/assets/erpnext/images/favicon.png",
	"splash_image": "/assets/erpnext/images/erp-icon.svg"
}

website_route_rules = [
	{"from_route": "/orders", "to_route": "Sales Order"},
	{"from_route": "/orders/<path:name>", "to_route": "order",
		"defaults": {
			"doctype": "Sales Order",
			"parents": [{"label": _("Orders"), "route": "orders"}]
		}
	},
	{"from_route": "/invoices", "to_route": "Sales Invoice"},
	{"from_route": "/invoices/<path:name>", "to_route": "order",
		"defaults": {
			"doctype": "Sales Invoice",
			"parents": [{"label": _("Invoices"), "route": "invoices"}]
		}
	},
	{"from_route": "/supplier-quotations", "to_route": "Supplier Quotation"},
	{"from_route": "/supplier-quotations/<path:name>", "to_route": "order",
		"defaults": {
			"doctype": "Supplier Quotation",
			"parents": [{"label": _("Supplier Quotation"), "route": "supplier-quotations"}]
		}
	},
	{"from_route": "/purchase-orders", "to_route": "Purchase Order"},
	{"from_route": "/purchase-orders/<path:name>", "to_route": "order",
		"defaults": {
			"doctype": "Purchase Order",
			"parents": [{"label": _("Purchase Order"), "route": "purchase-orders"}]
		}
	},
	{"from_route": "/purchase-invoices", "to_route": "Purchase Invoice"},
	{"from_route": "/purchase-invoices/<path:name>", "to_route": "order",
		"defaults": {
			"doctype": "Purchase Invoice",
			"parents": [{"label": _("Purchase Invoice"), "route": "purchase-invoices"}]
		}
	},
	{"from_route": "/quotations", "to_route": "Quotation"},
	{"from_route": "/quotations/<path:name>", "to_route": "order",
		"defaults": {
			"doctype": "Quotation",
			"parents": [{"label": _("Quotations"), "route": "quotations"}]
		}
	},
	{"from_route": "/shipments", "to_route": "Delivery Note"},
	{"from_route": "/shipments/<path:name>", "to_route": "order",
		"defaults": {
			"doctype": "Delivery Note",
			"parents": [{"label": _("Shipments"), "route": "shipments"}]
		}
	},
	{"from_route": "/rfq", "to_route": "Request for Quotation"},
	{"from_route": "/rfq/<path:name>", "to_route": "rfq",
		"defaults": {
			"doctype": "Request for Quotation",
			"parents": [{"label": _("Request for Quotation"), "route": "rfq"}]
		}
	},
	{"from_route": "/addresses", "to_route": "Address"},
	{"from_route": "/addresses/<path:name>", "to_route": "addresses",
		"defaults": {
			"doctype": "Address",
			"parents": [{"label": _("Addresses"), "route": "addresses"}]
		}
	},
	{"from_route": "/jobs", "to_route": "Job Opening"},
	{"from_route": "/admissions", "to_route": "Student Admission"},
	{"from_route": "/boms", "to_route": "BOM"},
	{"from_route": "/timesheets", "to_route": "Timesheet"},
	{"from_route": "/material-requests", "to_route": "Material Request"},
	{"from_route": "/material-requests/<path:name>", "to_route": "material_request_info",
		"defaults": {
			"doctype": "Material Request",
			"parents": [{"label": _("Material Request"), "route": "material-requests"}]
		}
	},
]

standard_portal_menu_items = [
	{"title": _("Personal Details"), "route": "/personal-details", "reference_doctype": "Patient", "role": "Patient"},
	{"title": _("Projects"), "route": "/project", "reference_doctype": "Project"},
	{"title": _("Request for Quotations"), "route": "/rfq", "reference_doctype": "Request for Quotation", "role": "Supplier"},
	{"title": _("Supplier Quotation"), "route": "/supplier-quotations", "reference_doctype": "Supplier Quotation", "role": "Supplier"},
	{"title": _("Purchase Orders"), "route": "/purchase-orders", "reference_doctype": "Purchase Order", "role": "Supplier"},
	{"title": _("Purchase Invoices"), "route": "/purchase-invoices", "reference_doctype": "Purchase Invoice", "role": "Supplier"},
	{"title": _("Quotations"), "route": "/quotations", "reference_doctype": "Quotation", "role":"Customer"},
	{"title": _("Orders"), "route": "/orders", "reference_doctype": "Sales Order", "role":"Customer"},
	{"title": _("Invoices"), "route": "/invoices", "reference_doctype": "Sales Invoice", "role":"Customer"},
	{"title": _("Shipments"), "route": "/shipments", "reference_doctype": "Delivery Note", "role":"Customer"},
	{"title": _("Issues"), "route": "/issues", "reference_doctype": "Issue", "role":"Customer"},
	{"title": _("Addresses"), "route": "/addresses", "reference_doctype": "Address"},
	{"title": _("Timesheets"), "route": "/timesheets", "reference_doctype": "Timesheet", "role":"Customer"},
	{"title": _("Lab Test"), "route": "/lab-test", "reference_doctype": "Lab Test", "role":"Patient"},
	{"title": _("Prescription"), "route": "/prescription", "reference_doctype": "Patient Encounter", "role":"Patient"},
	{"title": _("Patient Appointment"), "route": "/patient-appointments", "reference_doctype": "Patient Appointment", "role":"Patient"},
	{"title": _("Fees"), "route": "/fees", "reference_doctype": "Fees", "role":"Student"},
	{"title": _("Newsletter"), "route": "/newsletters", "reference_doctype": "Newsletter"},
	{"title": _("Admission"), "route": "/admissions", "reference_doctype": "Student Admission", "role": "Student"},
	{"title": _("Certification"), "route": "/certification", "reference_doctype": "Certification Application", "role": "Non Profit Portal User"},
	{"title": _("Material Request"), "route": "/material-requests", "reference_doctype": "Material Request", "role": "Customer"},
	{"title": _("Appointment Booking"), "route": "/book_appointment"},
]

default_roles = [
	{'role': 'Customer', 'doctype':'Contact', 'email_field': 'email_id'},
	{'role': 'Supplier', 'doctype':'Contact', 'email_field': 'email_id'},
	{'role': 'Student', 'doctype':'Student', 'email_field': 'student_email_id'},
]

has_website_permission = {
	"Sales Order": "erpnext.controllers.website_list_for_contact.has_website_permission",
	"Quotation": "erpnext.controllers.website_list_for_contact.has_website_permission",
	"Sales Invoice": "erpnext.controllers.website_list_for_contact.has_website_permission",
	"Supplier Quotation": "erpnext.controllers.website_list_for_contact.has_website_permission",
	"Purchase Order": "erpnext.controllers.website_list_for_contact.has_website_permission",
	"Purchase Invoice": "erpnext.controllers.website_list_for_contact.has_website_permission",
	"Material Request": "erpnext.controllers.website_list_for_contact.has_website_permission",
	"Delivery Note": "erpnext.controllers.website_list_for_contact.has_website_permission",
	"Issue": "erpnext.support.doctype.issue.issue.has_website_permission",
	"Timesheet": "erpnext.controllers.website_list_for_contact.has_website_permission",
	"Lab Test": "erpnext.healthcare.web_form.lab_test.lab_test.has_website_permission",
	"Patient Encounter": "erpnext.healthcare.web_form.prescription.prescription.has_website_permission",
	"Patient Appointment": "erpnext.healthcare.web_form.patient_appointments.patient_appointments.has_website_permission",
	"Patient": "erpnext.healthcare.web_form.personal_details.personal_details.has_website_permission"
}

dump_report_map = "erpnext.startup.report_data_map.data_map"

before_tests = "erpnext.setup.utils.before_tests"

standard_queries = {
	"Customer": "erpnext.controllers.queries.customer_query",
	"Healthcare Practitioner": "erpnext.healthcare.doctype.healthcare_practitioner.healthcare_practitioner.get_practitioner_list"
}

doc_events = {
	"User": {
		"after_insert": "frappe.contacts.doctype.contact.contact.update_contact",
		"validate": "erpnext.hr.doctype.employee.employee.validate_employee_role",
		"on_update": ["erpnext.hr.doctype.employee.employee.update_user_permissions",
			"erpnext.portal.utils.set_default_role"]
	},
	("Sales Taxes and Charges Template", 'Price List'): {
		"on_update": "erpnext.shopping_cart.doctype.shopping_cart_settings.shopping_cart_settings.validate_cart_settings"
	},
	"Website Settings": {
		"validate": "erpnext.portal.doctype.products_settings.products_settings.home_page_is_products"
	},
	"Sales Invoice": {
		"on_submit": ["erpnext.regional.create_transaction_log", "erpnext.regional.italy.utils.sales_invoice_on_submit"],
		"on_cancel": "erpnext.regional.italy.utils.sales_invoice_on_cancel",
		"on_trash": "erpnext.regional.check_deletion_permission"
	},
	"Purchase Invoice": {
		"validate": "erpnext.regional.india.utils.update_grand_total_for_rcm"
	},
	"Payment Entry": {
		"on_submit": ["erpnext.regional.create_transaction_log", "erpnext.accounts.doctype.payment_request.payment_request.update_payment_req_status"],
		"on_trash": "erpnext.regional.check_deletion_permission"
	},
	'Address': {
		'validate': ['erpnext.regional.india.utils.validate_gstin_for_india', 'erpnext.regional.italy.utils.set_state_code', 'erpnext.regional.india.utils.update_gst_category']
	},
	('Sales Invoice', 'Sales Order', 'Delivery Note', 'Purchase Invoice', 'Purchase Order', 'Purchase Receipt'): {
		'validate': ['erpnext.regional.india.utils.set_place_of_supply']
	},
	"Contact": {
		"on_trash": "erpnext.support.doctype.issue.issue.update_issue",
	},
}

naming_series_variables = {
	"FY": "erpnext.accounts.utils.parse_naming_series_variable",
	"CO": "erpnext.accounts.utils.parse_naming_series_variable",
}

scheduler_events = {
	"all": [
		"erpnext.projects.doctype.project.project.project_status_update_reminder",
		"erpnext.healthcare.doctype.patient_appointment.patient_appointment.set_appointment_reminder",
		"erpnext.vehicles.doctype.vehicle_booking_order.vehicle_booking_order.send_payment_overdue_notifications",
		"erpnext.vehicles.doctype.vehicle_booking_order.vehicle_booking_order.send_vehicle_anniversary_notifications",
		"erpnext.maintenance.doctype.maintenance_schedule.maintenance_schedule.send_maintenance_schedule_reminder_notifications",
		"erpnext.selling.doctype.customer.customer.send_customer_birthday_notifications",
	],
	"hourly": [
		'erpnext.hr.doctype.daily_work_summary_group.daily_work_summary_group.trigger_emails',
		"erpnext.accounts.doctype.subscription.subscription.process_all",
		"erpnext.erpnext_integrations.doctype.amazon_mws_settings.amazon_mws_settings.schedule_get_order_details",
		"erpnext.erpnext_integrations.doctype.plaid_settings.plaid_settings.automatic_synchronization",
		"erpnext.projects.doctype.project.project.hourly_reminder",
		"erpnext.projects.doctype.project.project.collect_project_status",
		"erpnext.hr.doctype.shift_type.shift_type.process_auto_attendance_for_all_shifts",
		"erpnext.support.doctype.issue.issue.set_service_level_agreement_variance",
		"erpnext.erpnext_integrations.fbr_pos_integration.post_fbr_pos_invoices_without_number",
	],
	"daily": [
		"erpnext.stock.reorder_item.reorder_item",
		"erpnext.support.doctype.issue.issue.auto_close_tickets",
		"erpnext.controllers.transaction_controller.set_invoice_as_overdue",
		"erpnext.vehicles.doctype.vehicle_booking_order.vehicle_booking_order.update_overdue_status",
		"erpnext.accounts.doctype.fiscal_year.fiscal_year.auto_create_fiscal_year",
		"erpnext.hr.doctype.employee.employee.send_employee_birthday_notification",
		"erpnext.hr.doctype.employee.employee.send_employee_anniversary_notification",
		"erpnext.projects.doctype.task.task.set_tasks_as_overdue",
		"erpnext.assets.doctype.asset.depreciation.post_depreciation_entries",
		"erpnext.hr.doctype.daily_work_summary_group.daily_work_summary_group.send_summary",
		"erpnext.stock.doctype.serial_no.serial_no.update_maintenance_status",
		"erpnext.buying.doctype.supplier_scorecard.supplier_scorecard.refresh_scorecards",
		"erpnext.setup.doctype.company.company.cache_companies_monthly_sales_history",
		"erpnext.assets.doctype.asset.asset.update_maintenance_status",
		"erpnext.assets.doctype.asset.asset.make_post_gl_entry",
		"erpnext.projects.doctype.project.project.send_project_status_email_to_users",
		"erpnext.quality_management.doctype.quality_review.quality_review.review",
		"erpnext.support.doctype.service_level_agreement.service_level_agreement.check_agreement_status",
		"erpnext.selling.doctype.quotation.quotation.set_expired_status",
		"erpnext.vehicles.doctype.vehicle_quotation.vehicle_quotation.set_expired_status",
		"erpnext.maintenance.doctype.maintenance_schedule.maintenance_schedule.create_opportunity_from_schedule",
	],
	"daily_long": [
		"erpnext.setup.doctype.email_digest.email_digest.send",
		"erpnext.manufacturing.doctype.bom_update_tool.bom_update_tool.update_latest_price_in_all_boms",
		"erpnext.hr.doctype.leave_ledger_entry.leave_ledger_entry.process_expired_allocation",
		"erpnext.hr.doctype.leave_encashment.leave_encashment.generate_leave_encashment"
	],
	"monthly_long": [
		"erpnext.accounts.deferred_revenue.convert_deferred_revenue_to_income",
		"erpnext.accounts.deferred_revenue.convert_deferred_expense_to_expense",
		"erpnext.hr.utils.allocate_earned_leaves"
	]
}

get_translated_dict = {
	("doctype", "Global Defaults"): "frappe.geo.country_info.get_translated_dict"
}

bot_parsers = [
	'erpnext.utilities.bot.FindItemBot',
]

get_site_info = 'erpnext.utilities.get_site_info'

payment_gateway_enabled = "erpnext.accounts.utils.create_payment_gateway_account"

jinja = {
	'methods': [
		'erpnext.stock.utils.format_item_name'
	]
}

regional_overrides = {
	'France': {
		'erpnext.tests.test_regional.test_method': 'erpnext.regional.france.utils.test_method'
	},
	'India': {
		'erpnext.tests.test_regional.test_method': 'erpnext.regional.india.utils.test_method',
		'erpnext.controllers.taxes_and_totals.get_itemised_tax_breakup_header': 'erpnext.regional.india.utils.get_itemised_tax_breakup_header',
		'erpnext.controllers.taxes_and_totals.get_itemised_tax_breakup_data': 'erpnext.regional.india.utils.get_itemised_tax_breakup_data',
		'erpnext.accounts.party.get_regional_address_details': 'erpnext.regional.india.utils.get_regional_address_details',
		'erpnext.hr.utils.calculate_annual_eligible_hra_exemption': 'erpnext.regional.india.utils.calculate_annual_eligible_hra_exemption',
		'erpnext.hr.utils.calculate_hra_exemption_for_period': 'erpnext.regional.india.utils.calculate_hra_exemption_for_period',
		'erpnext.accounts.doctype.purchase_invoice.purchase_invoice.make_regional_gl_entries': 'erpnext.regional.india.utils.make_regional_gl_entries'
	},
	'United Arab Emirates': {
		'erpnext.controllers.taxes_and_totals.update_itemised_tax_data': 'erpnext.regional.united_arab_emirates.utils.update_itemised_tax_data'
	},
	'Saudi Arabia': {
		'erpnext.controllers.taxes_and_totals.update_itemised_tax_data': 'erpnext.regional.united_arab_emirates.utils.update_itemised_tax_data'
	},
	'Italy': {
		'erpnext.controllers.taxes_and_totals.update_itemised_tax_data': 'erpnext.regional.italy.utils.update_itemised_tax_data',
		'erpnext.controllers.accounts_controller.validate_regional': 'erpnext.regional.italy.utils.sales_invoice_validate',
	}
}

# ERPNext doctypes for Global Search
global_search_doctypes = {
	"Default": [
		{"doctype": "Customer", "index": 0},
		{"doctype": "Supplier", "index": 1},
		{"doctype": "Item", "index": 2},
		{"doctype": "Warehouse", "index": 3},
		{"doctype": "Account", "index": 4},
		{"doctype": "Employee", "index": 5},
		{"doctype": "BOM", "index": 6},
		{"doctype": "Sales Invoice", "index": 7},
		{"doctype": "Sales Order", "index": 8},
		{"doctype": "Quotation", "index": 9},
		{"doctype": "Work Order", "index": 10},
		{"doctype": "Purchase Receipt", "index": 11},
		{"doctype": "Purchase Invoice", "index": 12},
		{"doctype": "Delivery Note", "index": 13},
		{"doctype": "Stock Entry", "index": 14},
		{"doctype": "Material Request", "index": 15},
		{"doctype": "Delivery Trip", "index": 16},
		{"doctype": "Pick List", "index": 17},
		{"doctype": "Salary Slip", "index": 18},
		{"doctype": "Leave Application", "index": 19},
		{"doctype": "Expense Claim", "index": 20},
		{"doctype": "Payment Entry", "index": 21},
		{"doctype": "Purchase Taxes and Charges Template", "index": 22},
		{"doctype": "Sales Taxes and Charges", "index": 23},
		{"doctype": "Asset", "index": 24},
		{"doctype": "Project", "index": 25},
		{"doctype": "Task", "index": 26},
		{"doctype": "Timesheet", "index": 27},
		{"doctype": "Issue", "index": 28},
		{"doctype": "Serial No", "index": 29},
		{"doctype": "Batch", "index": 30},
		{"doctype": "Branch", "index": 31},
		{"doctype": "Department", "index": 32},
		{"doctype": "Employee Grade", "index": 33},
		{"doctype": "Designation", "index": 34},
		{"doctype": "Job Opening", "index": 35},
		{"doctype": "Job Applicant", "index": 36},
		{"doctype": "Job Offer", "index": 37},
		{"doctype": "Salary Structure Assignment", "index": 38},
		{"doctype": "Appraisal", "index": 39},
		{"doctype": "Loan", "index": 40},
		{"doctype": "Maintenance Schedule", "index": 41},
		{"doctype": "Maintenance Visit", "index": 42},
		{"doctype": "Warranty Claim", "index": 43},
	]
}
