import frappe
from frappe import cstr


def format_vehicle_fields(doc):
	if doc.meta.has_field('vehicle_unregistered') and doc.meta.has_field('vehicle_license_plate'):
		if doc.get('vehicle_unregistered'):
			doc.vehicle_license_plate = ""

	if doc.meta.has_field('vehicle_chassis_no'):
		doc.vehicle_chassis_no = format_vehicle_id(doc.vehicle_chassis_no)
	if doc.meta.has_field('vehicle_engine_no'):
		doc.vehicle_engine_no = format_vehicle_id(doc.vehicle_engine_no)
	if doc.meta.has_field('vehicle_license_plate'):
		doc.vehicle_license_plate = format_vehicle_id(doc.vehicle_license_plate)


def format_vehicle_id(value):
	import re
	return re.sub(r"\s+", "", cstr(value).upper())


def get_vehicle_identifier(vehicle, vehicle_details=None):
	if not vehicle:
		return ""

	if not vehicle_details:
		vehicle_details = frappe.db.get_value("Vehicle", vehicle,
			("license_plate", "chassis_no"), as_dict=1, cache=1)

	if not vehicle_details:
		return vehicle

	if vehicle_details.license_plate:
		return vehicle_details.license_plate
	elif vehicle_details.chassis_no:
		return vehicle_details.chassis_no
	else:
		return vehicle
