# import frappe
from frappe.utils import flt
import requests


def get_exchange_rate_from_frankfurter(from_currency, to_currency, transaction_date):
	api_url = f"https://api.frankfurter.dev/v2/rates"
	response = requests.get(
		api_url,
		params={
			"date": transaction_date,
			"base": from_currency,
			"quotes": to_currency
		}
	)
	response.raise_for_status()
	data = response.json()
	if not data or not data[0]:
		return None

	rate = flt(data[0].get("rate"))
	return rate or None
