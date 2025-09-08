import frappe
from frappe.installer import install_app
from frappe.modules.patch_handler import get_patches_from_app, PatchType


def execute():
	if not frappe.db.exists("DocType", "FBR POS Settings"):
		return
	if not frappe.db.get_single_value("FBR POS Settings", "enable_fbr_pos", cache=False):
		return
	if "fbr_integration" in frappe.get_installed_apps():
		return

	frappe.reload_doctype("Sales Invoice")

	install_app("fbr_integration", set_as_patched=False, force=True)
	patches = get_patches_from_app("fbr_integration", PatchType.pre_model_sync)
	frappe.flags.final_patches += patches
