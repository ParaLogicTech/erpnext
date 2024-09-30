# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe


class website_maker(object):
	def __init__(self, args):
		self.args = args
		self.company = args.company_name
		self.tagline = args.company_tagline
		self.user = args.get('email')
		self.make_website_settings()

	def make_website_settings(self):
		# update in home page in settings
		website_settings = frappe.get_doc("Website Settings", "Website Settings")
		website_settings.brand_html = self.company
		website_settings.copyright = self.company
		website_settings.save()
