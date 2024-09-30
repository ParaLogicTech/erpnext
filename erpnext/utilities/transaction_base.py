# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
import frappe.share
from frappe import _
from frappe.utils import cstr, now_datetime, cint, flt, get_time, get_link_to_form, date_diff, add_days, getdate
from erpnext.controllers.status_updater import StatusUpdaterERP


class UOMMustBeIntegerError(frappe.ValidationError): pass


class TransactionBase(StatusUpdaterERP):
	def validate_posting_time(self):
		# set Edit Posting Date and Time to 1 while data import
		if frappe.flags.in_import and self.posting_date:
			self.set_posting_time = 1

		if not getattr(self, 'set_posting_time', None) and not self.get('amended_from'):
			now = now_datetime()
			self.posting_date = now.strftime('%Y-%m-%d')
			self.posting_time = now.strftime('%H:%M:%S.%f')
		elif self.posting_time:
			try:
				get_time(self.posting_time)
			except ValueError:
				frappe.throw(_('Invalid Posting Time'))

	def add_calendar_event(self, opts, force=False):
		if cstr(self.contact_by) != cstr(self._prev.contact_by) or \
				cstr(self.contact_date) != cstr(self._prev.contact_date) or force or \
				(hasattr(self, "ends_on") and cstr(self.ends_on) != cstr(self._prev.ends_on)):

			self.delete_events()
			self._add_calendar_event(opts)

	def delete_events(self):
		participations = frappe.get_all("Event Participants", filters={"reference_doctype": self.doctype, "reference_docname": self.name,
			"parenttype": "Event"}, fields=["name", "parent"])

		if participations:
			for participation in participations:
				total_participants = frappe.get_all("Event Participants", filters={"parenttype": "Event", "parent": participation.parent})

				if len(total_participants) <= 1:
					frappe.db.sql("delete from `tabEvent` where name='%s'" % participation.parent)

				frappe.db.sql("delete from `tabEvent Participants` where name='%s'" % participation.name)

	def _add_calendar_event(self, opts):
		opts = frappe._dict(opts)

		if self.contact_date:
			event = frappe.get_doc({
				"doctype": "Event",
				"owner": opts.owner or self.owner,
				"subject": opts.subject,
				"description": opts.description,
				"starts_on":  self.contact_date,
				"ends_on": opts.ends_on,
				"event_type": "Private"
			})

			event.append('event_participants', {
				"reference_doctype": self.doctype,
				"reference_docname": self.name
				}
			)

			event.insert(ignore_permissions=True)

			if frappe.db.exists("User", self.contact_by):
				frappe.share.add("Event", event.name, self.contact_by,
					flags={"ignore_share_permission": True})

	def validate_uom_is_integer(self, uom_field, qty_fields):
		validate_uom_is_integer(self, uom_field, qty_fields)

	def validate_with_previous_doc(self, ref, table_doctype=None):
		self.exclude_fields = ["conversion_factor", "uom"] if self.get('is_return') else []

		for prev_doctype, validator in ref.items():
			prev_is_child = validator.get("is_child_table")
			prev_parent_docs = []
			item_prev_docname_visited = []

			for row in self.get_all_children(table_doctype or self.doctype + " Item"):
				prev_docname = row.get(validator["ref_dn_field"])
				if prev_docname:
					if prev_is_child:
						self.compare_values({prev_doctype: [prev_docname]}, validator["compare_fields"], row)

						if prev_docname not in item_prev_docname_visited:
							item_prev_docname_visited.append(prev_docname)
						elif not validator.get("allow_duplicate_prev_row_id"):
							frappe.throw(_("Duplicate row {0} with same {1}").format(row.idx, prev_doctype))

					elif prev_docname:
						if prev_docname not in prev_parent_docs:
							prev_parent_docs.append(prev_docname)

			if prev_parent_docs:
				self.compare_values({prev_doctype: prev_parent_docs}, validator["compare_fields"])

	def compare_values(self, ref_doc, fields, doc=None):
		for reference_doctype, ref_dn_list in ref_doc.items():
			for reference_name in ref_dn_list:
				prevdoc_values = frappe.db.get_value(reference_doctype, reference_name,
					[d[0] for d in fields], as_dict=1)

				if not prevdoc_values:
					frappe.throw(_("Invalid reference {0} {1}").format(reference_doctype, reference_name))

				for field, condition in fields:
					if prevdoc_values[field] is not None and field not in self.exclude_fields:
						self.validate_value(field, condition, prevdoc_values[field], doc)

	def validate_rate_with_reference_doc(self, ref_details):
		buying_doctypes = ["Purchase Order", "Purchase Invoice", "Purchase Receipt"]

		if self.doctype in buying_doctypes:
			to_disable = "Maintain same rate throughout Purchase cycle"
			settings_page = "Buying Settings"
		else:
			to_disable = "Maintain same rate throughout Sales cycle"
			settings_page = "Selling Settings"

		for ref_dt, ref_dn_field, ref_link_field in ref_details:
			for d in self.get("items"):
				if d.get(ref_link_field):
					ref_rate = frappe.db.get_value(ref_dt + " Item", d.get(ref_link_field), "rate")

					if abs(flt(d.rate - ref_rate, d.precision("rate"))) >= .01:
						frappe.msgprint(_("Row #{0}: Rate must be same as {1}: {2} ({3} / {4}) ")
							.format(d.idx, ref_dt, d.get(ref_dn_field), d.rate, ref_rate))
						frappe.throw(_("To allow different rates, disable the {0} checkbox in {1}.")
							.format(frappe.bold(_(to_disable)),
							get_link_to_form(settings_page, settings_page, frappe.bold(settings_page))))

	def get_link_filters(self, for_doctype):
		if hasattr(self, "prev_link_mapper") and self.prev_link_mapper.get(for_doctype):
			fieldname = self.prev_link_mapper[for_doctype]["fieldname"]

			values = filter(None, tuple([item.as_dict()[fieldname] for item in self.items]))

			if values:
				ret = {
					for_doctype : {
						"filters": [[for_doctype, "name", "in", values]]
					}
				}
			else:
				ret = None
		else:
			ret = None

		return ret

	def validate_quotation_valid_till(self):
		if cint(self.quotation_validity_days) < 0:
			frappe.throw(_("Quotation Validity Days cannot be negative"))

		if cint(self.quotation_validity_days):
			self.valid_till = add_days(getdate(self.transaction_date), cint(self.quotation_validity_days) - 1)
		if not cint(self.quotation_validity_days) and self.valid_till:
			self.quotation_validity_days = date_diff(self.valid_till, self.transaction_date) + 1

		if self.valid_till and getdate(self.valid_till) < getdate(self.transaction_date):
			frappe.throw(_("Valid Till Date cannot be before transaction date"))

	def calculate_sales_team_contribution(self, net_total):
		if not self.meta.get_field("sales_team"):
			return

		net_total = flt(net_total)
		total_allocated_percentage = 0.0
		sales_team = self.get("sales_team") or []

		for sales_person in sales_team:
			self.round_floats_in(sales_person)

			sales_person.allocated_amount = flt(net_total * sales_person.allocated_percentage / 100.0,
				sales_person.precision("allocated_amount"))

			sales_person.incentives = flt(sales_person.allocated_amount * sales_person.commission_rate / 100.0,
				sales_person.precision("incentives"))

			total_allocated_percentage += sales_person.allocated_percentage

		if sales_team and total_allocated_percentage != 100.0:
			frappe.throw(_("Total allocated percentage for Sales Team should be 100%"))


def delete_events(ref_type, ref_name):
	events = frappe.db.sql_list(""" SELECT
			distinct `tabEvent`.name
		from
			`tabEvent`, `tabEvent Participants`
		where
			`tabEvent`.name = `tabEvent Participants`.parent
			and `tabEvent Participants`.reference_doctype = %s
			and `tabEvent Participants`.reference_docname = %s
		""", (ref_type, ref_name)) or []

	if events:
		frappe.delete_doc("Event", events, for_reload=True)


def validate_uom_is_integer(doc, uom_field, qty_fields, child_dt=None):
	if isinstance(qty_fields, str):
		qty_fields = [qty_fields]

	distinct_uoms = list(set([d.get(uom_field) for d in doc.get_all_children() if d.get(uom_field)]))
	integer_uoms = list(filter(lambda uom: frappe.get_cached_value("UOM", uom, "must_be_whole_number") or None, distinct_uoms))

	if not integer_uoms:
		return

	for d in doc.get_all_children(parenttype=child_dt):
		if d.get(uom_field) in integer_uoms:
			for f in qty_fields:
				qty = d.get(f)
				if qty:
					if abs(cint(qty) - flt(qty)) > 0.0000001:
						frappe.throw(_("Row {1}: Quantity ({0}) cannot be a fraction. To allow this, disable '{2}' in UOM {3}.") \
							.format(qty, d.idx, frappe.bold(_("Must be Whole Number")), frappe.bold(d.get(uom_field))),
								UOMMustBeIntegerError)
