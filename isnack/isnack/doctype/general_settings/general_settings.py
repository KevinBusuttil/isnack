# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class GeneralSettings(Document):
	pass


@frappe.whitelist()
def get_allowed_sales_item_groups():
	"""Return the list of Item Groups configured under General Settings → Sales.

	Read here (server-side) rather than client-side because General Settings is
	only readable by System Manager; sales users would otherwise get a permission
	error and the item filter would silently do nothing.
	"""
	rows = frappe.get_all(
		"Allowed Sales Item Group",
		filters={"parent": "General Settings", "parenttype": "General Settings"},
		fields=["item_group"],
		order_by="idx asc",
	)
	return [r.item_group for r in rows if r.item_group]
