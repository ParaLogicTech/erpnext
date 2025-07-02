import frappe
from frappe import _
from frappe.utils import cint


@frappe.whitelist()
def get_default_checklist_items(parentfield, default_checklist_dt, default_checklist_dn=None):
	meta = frappe.get_meta(default_checklist_dt)
	if not meta:
		frappe.throw(_("Invalid Default Checklist DocType"))

	df = meta.get_field(parentfield)
	if df.fieldtype != "Table" or df.options != "Checklist Item":
		frappe.throw(_("Invalid Checklist parentfield"))

	if not default_checklist_dn and meta.issingle:
		default_checklist_dn = default_checklist_dt

	if not default_checklist_dn:
		return []

	doc = frappe.get_cached_doc(default_checklist_dt, default_checklist_dn)
	checklist_items = [frappe._dict({
		"checklist_item": d.checklist_item, "is_check_mandatory": d.is_check_mandatory,
	}) for d in doc.get(parentfield)]

	return checklist_items


def validate_duplicate_checklist_items(checklist_items):
	visited = set()
	for d in checklist_items:
		if d.checklist_item in visited:
			frappe.throw(_("Row #{0}: Duplicate Checklist Item {1}").format(d.idx, frappe.bold(d.checklist_item)))

		visited.add(d.checklist_item)


def set_missing_checklist(doc, parentfield, default_checklist_dt, default_checklist_dn=None):
	if not doc.get(parentfield):
		checklist = get_default_checklist_items(parentfield, default_checklist_dt, default_checklist_dn)
		for d in checklist:
			doc.append(parentfield, {
				'checklist_item': d.checklist_item,
				'is_check_mandatory': cint(d.is_check_mandatory),
				'checklist_item_checked': 0
			})


def set_updated_checklist(doc, parentfield, default_checklist_dt, default_checklist_dn=None):
	def add_row(row, is_custom=0):
		if isinstance(row, str):
			row = frappe._dict({'checklist_item': d})

		if row.checklist_item in existing_items:
			new_row = existing_items[row.checklist_item]
			new_row.checklist_item_checked = 0
			new_row.is_custom_checklist_item = cint(is_custom)
			doc.get(parentfield).append(new_row)
		else:
			doc.append(parentfield, {
				'checklist_item': row.checklist_item,
				'is_check_mandatory': row.is_check_mandatory,
				'checklist_item_checked': 0,
				'is_custom_checklist_item': cint(is_custom)
			})

	checked_items = [d.checklist_item for d in doc.get(parentfield) if d.get('checklist_item_checked')]
	custom_items = [d for d in doc.get(parentfield) if d.get('is_custom_checklist_item')]
	existing_items = {d.checklist_item: d for d in doc.get(parentfield)}

	updated_checklist = get_default_checklist_items(parentfield, default_checklist_dt, default_checklist_dn)
	doc.set(parentfield, [])

	# Add settings items first
	for d in updated_checklist:
		add_row(d)

	# Add previously set custom items
	for d in custom_items:
		if d.checklist_item not in [e.checklist_item for e in doc.get(parentfield)]:
			add_row(d, is_custom=1)

	# Add checked items that are now removed
	for d in checked_items:
		if d not in [e.checklist_item for e in doc.get(parentfield)]:
			add_row(d, is_custom=1)

	# Reset idx and set checked
	for i, d in enumerate(doc.get(parentfield)):
		d.idx = i + 1
		if d.checklist_item in checked_items:
			d.checklist_item_checked = 1


def validate_mandatory_checklist(checklist_items, error_message=None):
	unchecked_mandatory_items = get_mandatory_unchecked_items(checklist_items)
	if not unchecked_mandatory_items:
		return

	list_str = "".join([f"<li>{item}</li>" for item in unchecked_mandatory_items])
	list_str = f"<ol>{list_str}</ol>"

	if not error_message:
		error_message = _("The following checklist items are mandatory")

	frappe.throw(f"{error_message}<br><br>{list_str}")


def get_mandatory_unchecked_items(checklist_items):
	if not checklist_items:
		return

	mandatory_checklist_items = set([d.checklist_item for d in checklist_items if d.get("is_check_mandatory")])
	if not mandatory_checklist_items:
		return

	checked_items = set([d.checklist_item for d in checklist_items if d.checklist_item_checked])
	return mandatory_checklist_items - checked_items


def clear_empty_checklist(doc, parentfield):
	if not any([d.checklist_item_checked for d in doc.get(parentfield)]):
		doc.set(parentfield, [])
