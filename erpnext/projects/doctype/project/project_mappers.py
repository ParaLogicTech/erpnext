import frappe
from frappe import _
from frappe.utils import flt, cint, getdate
from frappe.model.utils import get_fetch_values
from erpnext.projects.doctype.project.project import (
	get_project_details,
	set_depreciation_in_invoice_items,
	get_service_template_ordered_set,
	get_service_template_quoted_set,
	get_service_template_requested_set,
)
import json


@frappe.whitelist()
def make_sales_invoice(project_name, target_doc=None, depreciation_type=None, bill_multiple_projects=None):
	from erpnext.controllers.queries import _get_proforma_invoices_to_be_billed

	if frappe.flags.args and bill_multiple_projects is None:
		bill_multiple_projects = frappe.flags.args.bill_multiple_projects

	bill_multiple_projects = cint(bill_multiple_projects)

	proforma_invoice_filters = {"project": project_name}
	if depreciation_type:
		project_details = frappe.db.get_value("Project", project_name,
			["customer", "bill_to", "insurance_company"], as_dict=1)
		if depreciation_type == "Depreciation Amount Only":
			proforma_invoice_filters["bill_to"] = project_details.customer
		elif depreciation_type == "After Depreciation Amount":
			proforma_invoice_filters["bill_to"] = project_details.bill_to or project_details.insurance_company

	proforma_invoices = _get_proforma_invoices_to_be_billed(filters=proforma_invoice_filters)

	if proforma_invoices:
		return make_sales_invoice_from_proforma(project_name, proforma_invoices, target_doc, bill_multiple_projects)
	else:
		return make_sales_invoice_from_orders(project_name, target_doc, depreciation_type, bill_multiple_projects)


def make_sales_invoice_from_proforma(project_name, proforma_invoices, target_doc=None, bill_multiple_projects=None):
	from erpnext.accounts.doctype.proforma_invoice.proforma_invoice import make_sales_invoice as invoice_from_proforma_invoice

	project = frappe.get_doc("Project", project_name)
	project_details = get_project_details(project, "Sales Invoice")

	# Make Sales Invoice Target Document
	if target_doc and isinstance(target_doc, str):
		target_doc = json.loads(target_doc)

	target_doc = frappe.get_doc(target_doc) if target_doc else frappe.new_doc("Sales Invoice")
	if not bill_multiple_projects:
		set_default_transaction_type(target_doc)
		set_project_details_in_transaction(target_doc, project_details, project)

	# Map Proforma Invoices
	for d in proforma_invoices:
		target_doc = invoice_from_proforma_invoice(d.name, target_doc=target_doc, only_items=bill_multiple_projects,
			skip_postprocess=bill_multiple_projects, set_advances=False)

	# Postprocess
	if not bill_multiple_projects:
		set_cash_or_credit(target_doc, project)
		target_doc.run_method("postprocess_after_mapping")
		set_advances(target_doc, project)

	if bill_multiple_projects:
		frappe.flags.postprocess_after_mapping = postprocess_bill_multiple_projects

	project.check_po_no_is_set(target_doc)
	project.validate_for_transaction(target_doc)

	return target_doc


def make_sales_invoice_from_orders(project_name, target_doc=None, depreciation_type=None, bill_multiple_projects=None):
	def get_filters():
		filters = {"project": project.name}
		if project.company:
			filters['company'] = project.company

		return filters

	def map_delivery_notes(target, only_items=False, skip_postprocess=False):
		from erpnext.controllers.queries import _get_delivery_notes_to_be_billed
		from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice as invoice_from_delivery_note

		delivery_note_filters = get_filters()
		delivery_note_filters['is_return'] = 0
		delivery_notes = _get_delivery_notes_to_be_billed(filters=delivery_note_filters)

		for d in delivery_notes:
			target = invoice_from_delivery_note(d.name, target_doc=target, only_items=only_items,
				skip_postprocess=skip_postprocess)

		return target

	def map_sales_orders(target, only_items=False, skip_postprocess=False):
		from erpnext.controllers.queries import _get_sales_orders_to_be_billed
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice as invoice_from_sales_order

		sales_order_filters = get_filters()
		sales_orders = _get_sales_orders_to_be_billed(filters=sales_order_filters)

		for d in sales_orders:
			target = invoice_from_sales_order(d.name, target_doc=target, only_items=only_items,
				skip_postprocess=skip_postprocess)

		return target

	def set_terms_template():
		if project.invoice_terms_template:
			target_doc.tc_name = project.invoice_terms_template

	project = frappe.get_doc("Project", project_name)
	project_details = get_project_details(project, "Sales Invoice")

	# Make Sales Invoice Target Document
	if target_doc and isinstance(target_doc, str):
		target_doc = json.loads(target_doc)

	target_doc = frappe.get_doc(target_doc) if target_doc else frappe.new_doc("Sales Invoice")

	if not bill_multiple_projects:
		set_default_transaction_type(target_doc)
		set_project_details_in_transaction(target_doc, project_details, project)

	has_depreciation_rate = (
		project.default_depreciation_percentage
		or project.default_underinsurance_percentage
		or project.non_standard_depreciation
		or project.non_standard_underinsurance
	)

	has_excess_amount = project.insurance_excess_amount or project.insurance_excess_percentage

	if has_excess_amount and not has_depreciation_rate and depreciation_type != "After Depreciation Amount":
		pass
	else:
		target_doc = map_delivery_notes(target_doc, only_items=bill_multiple_projects, skip_postprocess=bill_multiple_projects)
		target_doc = map_sales_orders(target_doc, only_items=bill_multiple_projects, skip_postprocess=bill_multiple_projects)

	if not bill_multiple_projects:
		remove_taxes_from_transaction(target_doc)
		set_project_details_in_transaction(target_doc, project_details, project)
		set_depreciation_type_and_customer(target_doc, project, depreciation_type, has_depreciation_rate, has_excess_amount)
		set_cash_or_credit(target_doc, project)
		set_contact_and_address_in_transaction(target_doc, project)
		set_po_no_in_transaction(target_doc, project)
		set_missing_insurance_details(target_doc)
		set_sales_person_in_target_doc(target_doc, project)
		set_terms_template()
		set_invoice_remarks(target_doc, project)

		target_doc.run_method("set_missing_values")
		set_depreciation_in_invoice_items(target_doc.get('items'), project, force=True)
		target_doc.run_method("postprocess_after_mapping", reset_taxes=True)

		set_advances(target_doc, project)

	if bill_multiple_projects:
		frappe.flags.postprocess_after_mapping = postprocess_bill_multiple_projects

	project.check_po_no_is_set(target_doc)
	project.validate_for_transaction(target_doc)

	return target_doc


@frappe.whitelist()
def make_proforma_invoice(project_name, target_doc=None, depreciation_type=None):
	def get_filters():
		filters = {"project": project.name}
		if project.company:
			filters['company'] = project.company

		return filters

	def map_delivery_notes(target, only_items=False, skip_postprocess=False):
		from erpnext.controllers.queries import _get_delivery_notes_to_be_billed
		from erpnext.stock.doctype.delivery_note.delivery_note import make_proforma_invoice as invoice_from_delivery_note

		delivery_note_filters = get_filters()
		delivery_note_filters['is_return'] = 0
		delivery_notes = _get_delivery_notes_to_be_billed(filters=delivery_note_filters)

		for d in delivery_notes:
			target = invoice_from_delivery_note(d.name, target_doc=target, only_items=only_items,
				skip_postprocess=skip_postprocess)

		return target

	def map_sales_orders(target, only_items=False, skip_postprocess=False):
		from erpnext.controllers.queries import _get_sales_orders_to_be_billed
		from erpnext.selling.doctype.sales_order.sales_order import make_proforma_invoice as invoice_from_sales_order

		sales_order_filters = get_filters()
		sales_orders = _get_sales_orders_to_be_billed(filters=sales_order_filters)

		for d in sales_orders:
			target = invoice_from_sales_order(d.name, target_doc=target, only_items=only_items,
				skip_postprocess=skip_postprocess)

		return target

	project = frappe.get_doc("Project", project_name)
	project_details = get_project_details(project, "Proforma Invoice")

	# Make Proforma Invoice Target Document
	if target_doc and isinstance(target_doc, str):
		target_doc = json.loads(target_doc)

	target_doc = frappe.get_doc(target_doc) if target_doc else frappe.new_doc("Proforma Invoice")

	set_default_transaction_type(target_doc)
	set_project_details_in_transaction(target_doc, project_details, project)

	has_depreciation_rate = (
		project.default_depreciation_percentage
		or project.default_underinsurance_percentage
		or project.non_standard_depreciation
		or project.non_standard_underinsurance
	)

	has_excess_amount = project.insurance_excess_amount or project.insurance_excess_percentage

	if has_excess_amount and not has_depreciation_rate and depreciation_type != "After Depreciation Amount":
		pass
	else:
		target_doc = map_delivery_notes(target_doc)
		target_doc = map_sales_orders(target_doc)

	remove_taxes_from_transaction(target_doc)
	set_project_details_in_transaction(target_doc, project_details, project)
	set_depreciation_type_and_customer(target_doc, project, depreciation_type, has_depreciation_rate, has_excess_amount)
	set_contact_and_address_in_transaction(target_doc, project)
	set_po_no_in_transaction(target_doc, project)
	set_missing_insurance_details(target_doc)
	set_sales_person_in_target_doc(target_doc, project)
	set_invoice_remarks(target_doc, project)

	target_doc.run_method("set_missing_values")
	set_depreciation_in_invoice_items(target_doc.get('items'), project, force=True)
	target_doc.run_method("postprocess_after_mapping", reset_taxes=True)

	set_advances(target_doc, project)

	project.validate_for_transaction(target_doc)

	return target_doc


def set_depreciation_type_and_customer(target_doc, project, depreciation_type, has_depreciation_rate, has_excess_amount):
	if depreciation_type and (has_depreciation_rate or has_excess_amount):
		if has_depreciation_rate:
			target_doc.depreciation_type = depreciation_type

		if depreciation_type == "Depreciation Amount Only":
			target_doc.bill_to = target_doc.customer
		elif depreciation_type == "After Depreciation Amount":
			if not project.bill_to and project.insurance_company:
				target_doc.bill_to = project.insurance_company

		insurance_excess_item = frappe.get_cached_value("Projects Settings", None, "insurance_excess_item")
		insurance_excess_item_name = frappe.get_cached_value("Item", insurance_excess_item, "item_name") or _("Insurance Excess")

		total_excess = flt(project.insurance_excess_amount) + flt(project.additional_insurance_excess_amount)
		positive_excess, negative_excess = project.get_insurance_excess_billed(
			include_proforma_invoices=target_doc.doctype == "Proforma Invoice"
		)
		billed_excess = negative_excess if depreciation_type == "After Depreciation Amount" else positive_excess
		balance_excess = flt(total_excess - billed_excess, project.precision("insurance_excess_amount"))

		if billed_excess:
			if balance_excess > 0:
				row = target_doc.append("items", frappe.new_doc(target_doc.doctype + " Item"))
				row.item_code = insurance_excess_item
				row.qty = 1
				row.price_list_rate = 0
				row.rate = balance_excess
				if depreciation_type == "After Depreciation Amount":
					row.rate *= -1
		else:
			if flt(project.insurance_excess_amount):
				row = target_doc.append("items", frappe.new_doc(target_doc.doctype + " Item"))
				row.item_code = insurance_excess_item
				row.qty = 1
				row.price_list_rate = 0
				row.rate = flt(project.insurance_excess_amount)
				if depreciation_type == "After Depreciation Amount":
					row.rate *= -1

			if flt(project.additional_insurance_excess_amount):
				row = target_doc.append("items", frappe.new_doc(target_doc.doctype + " Item"))
				row.item_code = insurance_excess_item
				row.item_name = insurance_excess_item_name + " ({0})".format(
					project.get_formatted("insurance_excess_percentage", precision=1)
				)
				row.qty = 1
				row.price_list_rate = 0
				row.rate = flt(project.additional_insurance_excess_amount)
				if depreciation_type == "After Depreciation Amount":
					row.rate *= -1


def postprocess_bill_multiple_projects(target_doc):
	target_doc.ignore_pricing_rule = 1
	target_doc.bill_multiple_projects = 1
	target_doc.run_method("postprocess_after_mapping")


@frappe.whitelist()
def make_delivery_note(project_name):
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

	project = frappe.get_doc("Project", project_name)
	project_details = get_project_details(project, "Delivery Note")

	# Create Delivery Note
	target_doc = frappe.new_doc("Delivery Note")

	# Set Project Details
	set_default_transaction_type(target_doc, force=True)
	set_project_details_in_transaction(target_doc, project_details, project)

	# Get Sales Orders
	sales_order_filters = {
		"docstatus": 1,
		"status": ["not in", ["Closed", "On Hold"]],
		"delivery_status": ["=", "To Deliver"],
		"project": project.name,
		"company": project.company,
		"skip_delivery_note": 0,
	}
	sales_orders = frappe.get_all("Sales Order", filters=sales_order_filters)
	for d in sales_orders:
		target_doc = make_delivery_note(d.name, target_doc=target_doc)

	# Remove Taxes (so they are reloaded)
	remove_taxes_from_transaction(target_doc)

	# Set Project Details
	for k, v in project_details.items():
		if target_doc.meta.has_field(k):
			target_doc.set(k, v)

	set_sales_person_in_target_doc(target_doc, project)

	# Missing Values and Forced Values
	target_doc.run_method("postprocess_after_mapping", reset_taxes=True)

	project.validate_for_transaction(target_doc)

	return target_doc


@frappe.whitelist()
def make_sales_order(project_name, items_type=None, without_items=False, skip_postprocess=False):
	from erpnext.projects.doctype.service_template.service_template import add_service_template_items

	project = frappe.get_doc("Project", project_name)
	project_details = get_project_details(project, "Sales Order")

	# Create Sales Order
	target_doc = frappe.new_doc("Sales Order")
	target_doc.company = project.company
	target_doc.project = project.name
	target_doc.delivery_date = project.expected_delivery_date

	sales_order_print_heading = frappe.get_cached_value("Projects Settings", None, "sales_order_print_heading")
	if sales_order_print_heading:
		target_doc.select_print_heading = sales_order_print_heading

	set_default_transaction_type(target_doc, force=True)

	# Set Project Details
	for k, v in project_details.items():
		if target_doc.meta.has_field(k):
			target_doc.set(k, v)

	if not without_items:
		# Get Service Template Items
		for d in project.service_templates:
			if not d.get('sales_order') and d.service_template:
				target_doc = add_service_template_items(target_doc, d.service_template,
					applies_to_item=project.applies_to_item, applies_to_customer=project.customer,
					check_duplicate=False, service_template_detail=d, items_type=items_type)

		# Remove already ordered items
		service_template_ordered_set = get_service_template_ordered_set(project, group_by_item_type=True)
		to_remove = []
		for d in target_doc.get('items'):
			is_stock_item = 0
			if d.item_code:
				is_stock_item = cint(frappe.get_cached_value("Item", d.item_code, 'is_stock_item'))

			if d.service_template_detail and (d.service_template_detail, is_stock_item) in service_template_ordered_set:
				to_remove.append(d)

		for d in to_remove:
			target_doc.remove(d)
		for i, d in enumerate(target_doc.items):
			d.idx = i + 1

	set_sales_person_in_target_doc(target_doc, project)

	# Missing Values and Forced Values
	if not skip_postprocess:
		target_doc.run_method("postprocess_after_mapping", reset_taxes=True)

	project.validate_for_transaction(target_doc)

	return target_doc


@frappe.whitelist()
def make_quotation(project_name, items_type=None):
	from erpnext.projects.doctype.service_template.service_template import add_service_template_items

	project = frappe.get_doc("Project", project_name)
	project_details = get_project_details(project, "Quotation")

	# Create Sales Order
	target_doc = frappe.new_doc("Quotation")
	target_doc.company = project.company
	target_doc.project = project.name
	target_doc.delivery_date = project.expected_delivery_date if getdate(project.expected_delivery_date) >= getdate() else None

	set_default_transaction_type(target_doc, force=True)

	# Set Project Details
	for k, v in project_details.items():
		if target_doc.meta.has_field(k):
			target_doc.set(k, v)

	# Get Service Template Items
	for d in project.service_templates:
		if not d.get('sales_order') and d.service_template:
			target_doc = add_service_template_items(target_doc, d.service_template,
				applies_to_item=project.applies_to_item, applies_to_customer=project.customer,
				check_duplicate=False, service_template_detail=d, items_type=items_type)

	set_sales_person_in_target_doc(target_doc, project)

	# Remove already ordered items
	service_template_quoted_set = get_service_template_quoted_set(project)
	service_template_ordered_set = get_service_template_ordered_set(project)

	to_remove = []
	for d in target_doc.get('items'):
		if (
			d.service_template_detail
			and (
				d.service_template_detail in service_template_quoted_set
				or d.service_template_detail in service_template_ordered_set
			)
		):
			to_remove.append(d)

	for d in to_remove:
		target_doc.remove(d)
	for i, d in enumerate(target_doc.items):
		d.idx = i + 1

	# Set Previous Orders
	sales_orders = frappe.get_all("Sales Order", filters={
		"project": project.name, "status": ["!=", "Closed"], "docstatus": 1
	}, pluck="name", order_by="transaction_date, creation")
	for sales_order in sales_orders:
		target_doc.append("previous_orders", {"previous_sales_order": sales_order})

	# Missing Values and Forced Values
	target_doc.run_method("postprocess_after_mapping", reset_taxes=True)

	project.validate_for_transaction(target_doc)

	return target_doc


@frappe.whitelist()
def make_material_request(project_name):
	from erpnext.projects.doctype.service_template.service_template import add_service_template_items

	project = frappe.get_doc("Project", project_name)
	project_details = get_project_details(project, "Material Request")

	# Create Material Request
	target_doc = frappe.new_doc("Material Request")
	target_doc.material_request_type = "Material Issue"
	target_doc.company = project.company
	target_doc.project = project.name
	target_doc.schedule_date = project.expected_delivery_date

	# Set Project Details
	for k, v in project_details.items():
		if target_doc.meta.has_field(k):
			target_doc.set(k, v)

	# Get Service Template Items
	for d in project.service_templates:
		if not d.get('sales_order') and d.service_template:
			target_doc = add_service_template_items(target_doc, d.service_template,
				applies_to_item=project.applies_to_item, applies_to_customer=project.customer,
				check_duplicate=False, service_template_detail=d, items_type="stock")

	# Remove already ordered items
	service_template_requested_set = get_service_template_requested_set(project)
	to_remove = []
	for d in target_doc.get('items'):
		if d.service_template_detail and d.service_template_detail in service_template_requested_set:
			to_remove.append(d)

	for d in to_remove:
		target_doc.remove(d)
	for i, d in enumerate(target_doc.items):
		d.idx = i + 1

	# Missing Values and Forced Values
	target_doc.run_method("postprocess_after_mapping")

	project.validate_for_transaction(target_doc)

	return target_doc


@frappe.whitelist()
def make_stock_entry(project_name, purpose):
	from erpnext.stock.doctype.material_request.material_request import make_stock_entry

	if not purpose:
		frappe.throw(_("Purpose not provided"))
	if purpose not in ("Material Issue", "Material Receipt"):
		frappe.throw(_("Invalid Purpose {0}").format(purpose))

	project = frappe.get_doc("Project", project_name)
	project_details = get_project_details(project, "Stock Entry", purpose=purpose)

	# Create Stock Entry
	target_doc = frappe.new_doc("Stock Entry")
	target_doc.company = project.company
	target_doc.project = project.name
	target_doc.purpose = purpose

	# Set Project Details
	for k, v in project_details.items():
		if target_doc.meta.has_field(k):
			target_doc.set(k, v)

	# Map Material Requests
	if purpose == "Material Issue":
		material_request_filters = {
			"docstatus": 1,
			"material_request_type": "Material Issue",
			"status": ["!=", "Stopped"],
			"order_status": "To Order",
			"project": project.name,
			"company": project.company,
		}
		material_requests = frappe.get_all("Material Request", filters=material_request_filters)
		for d in material_requests:
			target_doc = make_stock_entry(d.name, target_doc=target_doc)
	elif purpose == "Material Receipt":
		returnable = get_returnable_consumables(project.name)
		for d in returnable:
			row = target_doc.append("items", frappe.new_doc("Stock Entry Detail"))
			row.update(d)
			row.qty = 0

	# Set Project Details
	for k, v in project_details.items():
		if target_doc.meta.has_field(k):
			target_doc.set(k, v)

	# Missing Values and Forced Values
	target_doc.set_stock_entry_type()
	target_doc.run_method("postprocess_after_mapping")

	project.validate_for_transaction(target_doc)

	return target_doc


@frappe.whitelist()
def make_payment_entry(project_name, is_refund=False):
	project = frappe.get_doc("Project", project_name)

	is_refund = cint(is_refund)

	pe = frappe.new_doc("Payment Entry")
	pe.posting_date = getdate()
	pe.company = project.company
	pe.branch = project.branch
	pe.cost_center = project.cost_center
	pe.project = project.name

	pe.payment_type = "Pay" if is_refund else "Receive"
	pe.party_type = "Customer"
	pe.party = project.bill_to or project.customer
	pe.contact_person = project.billing_contact_person if project.bill_to else project.contact_person

	frappe.utils.call_hook_method("get_payment_entry", project, pe)

	if is_refund:
		payment_entries = project.get_advance_payment_entries()
		payment_entries = [d for d in payment_entries if d.payment_type == "Receive" and d.unallocated_amount > 0]

		for d in payment_entries:
			row = pe.append("references", {
				"reference_doctype": "Payment Entry",
				"reference_name": d.name,
			})
			pe.set_reference_row_details(row)

	set_taxes = frappe.get_cached_value("Accounts Settings", None, "apply_taxes_on_advance_payment")
	pe.run_method("postprocess_after_mapping", reset_taxes=set_taxes)

	return pe


@frappe.whitelist()
def create_service_warranties(project_name):
	project = frappe.get_doc("Project", project_name)

	warranty_templates = [d for d in project.service_templates if d.includes_service_warranty]
	warranty_templates_not_created = [d for d in warranty_templates if not d.has_service_warranty]
	if not warranty_templates:
		frappe.throw(_("{0} does not have Service Templates with Service Warranty included").format(
			frappe.get_desk_link("Project", project.name)
		))
	if not warranty_templates_not_created:
		frappe.throw(_("Service Warranty already created for {0}").format(
			frappe.get_desk_link("Project", project.name)
		))

	docs = []
	for row in warranty_templates_not_created:
		doc = frappe.new_doc("Service Warranty")
		doc.project = project.name
		doc.service_template = row.service_template
		doc.service_template_detail = row.name
		doc.posting_date = getdate()
		doc.valid_from = getdate(project.ready_to_close_dt)
		doc.submit()

		docs.append(doc)

	list_txt = "".join([
		"<li>{0}: {1}</li>".format(
			doc.service_template_name, frappe.utils.get_link_to_form("Service Warranty", doc.name)
		)
		for doc in docs
	])
	list_txt = f"<ul>{list_txt}</ul>"
	frappe.msgprint(_("Service Warranty created:<br><br>{0}").format(list_txt))

	return [doc.name for doc in docs]


def get_returnable_consumables(project):
	material_issue_data = frappe.db.sql("""
		select i.item_code, sum(i.qty) as qty, i.uom
		from `tabStock Entry Detail` i
		inner join `tabStock Entry` ste on ste.name = i.parent
		where ste.project = %s and ste.docstatus = 1 and ste.purpose = 'Material Issue'
		group by i.item_code, i.uom
	""", project, as_dict=1)

	material_receipt_data = frappe.db.sql("""
		select i.item_code, sum(i.qty) as qty, i.uom
		from `tabStock Entry Detail` i
		inner join `tabStock Entry` ste on ste.name = i.parent
		where ste.project = %s and ste.docstatus = 1 and ste.purpose = 'Material Receipt'
		group by i.item_code, i.uom
	""", project, as_dict=1)

	material_map = {}
	for d in material_issue_data:
		key = (d.item_code, d.uom)
		row = material_map.setdefault(key, frappe._dict({"item_code": d.item_code, "uom": d.uom, "qty": 0}))
		row.qty += d.qty

	for d in material_receipt_data:
		key = (d.item_code, d.uom)
		if key not in material_map:
			continue

		row = material_map[key]
		row.qty -= d.qty

	out = list(material_map.values())
	for d in out:
		d.qty = flt(d.qty, frappe.get_precision("Stock Entry Detail", "qty"))

	out = [d for d in out if d.qty > 0]
	return out


def set_project_details_in_transaction(target_doc, project_details, project):
	target_doc.company = project.company
	target_doc.project = project.name

	for k, v in project_details.items():
		if target_doc.meta.has_field(k):
			target_doc.set(k, v)


def set_cash_or_credit(target_doc, project):
	invoice_bill_to = target_doc.bill_to or target_doc.customer
	project_bill_to = project.bill_to or project.customer
	if target_doc.insurance_company and invoice_bill_to == target_doc.insurance_company:
		target_doc.is_pos = 0
	elif target_doc.insurance_company and invoice_bill_to != project_bill_to:
		target_doc.is_pos = frappe.get_cached_value("Customer", invoice_bill_to, "cash_billing") or project.cash_billing
	else:
		target_doc.is_pos = project.cash_billing


def set_contact_and_address_in_transaction(target_doc, project):
	target_bill_to = target_doc.bill_to or target_doc.customer
	if project.bill_to and target_bill_to == project.bill_to:
		target_doc.contact_person = project.billing_contact_person
		target_doc.customer_address = project.billing_address
	else:
		target_doc.contact_person = project.contact_person
		target_doc.contact_mobile = project.contact_mobile
		target_doc.contact_phone = project.contact_phone
		target_doc.customer_address = project.customer_address


def set_po_no_in_transaction(target_doc, project):
	target_bill_to = target_doc.bill_to or target_doc.customer
	if project.po_no and not project.bill_to or target_bill_to == project.bill_to:
		target_doc.po_no = project.po_no
		target_doc.po_date = project.po_date


def remove_taxes_from_transaction(target_doc):
	target_doc.taxes_and_charges = None
	target_doc.taxes = []


def set_missing_insurance_details(target_doc):
	target_doc.update(get_fetch_values(target_doc.doctype, 'insurance_company', target_doc.insurance_company))


def set_invoice_remarks(target_doc, project):
	if project.get("invoice_remarks"):
		target_doc.remarks = project.get("invoice_remarks")


def set_advances(target_doc, project):
	target_doc.set_advances(against_project=project.name)
	if target_doc.advances:
		target_doc.run_method("calculate_taxes_and_totals")


def set_sales_person_in_target_doc(target_doc, project):
	if project.service_advisor and target_doc.meta.has_field("sales_team"):
		target_doc.sales_team = []
		target_doc.append("sales_team", {
			"sales_person": project.service_advisor,
			"allocated_percentage": 100
		})


def set_default_transaction_type(target_doc, force=False):
	default_transaction_type = frappe.get_cached_value("Projects Settings", None, "default_sales_transaction_type")
	if not default_transaction_type:
		return

	if not target_doc.transaction_type or force:
		target_doc.transaction_type = default_transaction_type
