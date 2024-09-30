import frappe
from frappe import _
from frappe.utils import flt
from crm.crm.doctype.territory.territory import Territory


class TerritoryERP(Territory):
	def validate(self):
		super().validate()
		for d in self.get('targets') or []:
			if not flt(d.target_qty) and not flt(d.target_alt_uom_qty) and not flt(d.target_amount):
				frappe.throw(_("Row {0}: Either Target Stock Qty or Target Contents Qty or Target Amount is mandatory.")
					.format(d.idx))
