import frappe
from frappe import _


def override_user_dashboard(data):
	data.setdefault("non_standard_fieldnames", {})
	data["non_standard_fieldnames"]["Employee"] = "user_id"

	profile_items = ["Employee"]

	ref_section = [d for d in data["transactions"] if d["label"] == _("Profile")]
	if ref_section:
		ref_section = ref_section[0]
		ref_section["items"] = ref_section["items"] + profile_items
	else:
		data["transactions"].append({
			"label": _("Profile"),
			"items": profile_items,
		})

	return data
