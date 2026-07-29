# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils.nestedset import get_descendants_of


class GeneralSettings(Document):
	pass


def get_packaging_item_groups() -> set[str]:
	"""Return the Item Groups configured under General Settings → Packing.

	Item Group is a tree, so each configured group brings its descendants with
	it: picking "Packaging Materials" also covers a "Packaging Materials →
	Pallets" child added later, which is what someone selecting the parent
	expects. An empty set means nothing is treated as packaging.
	"""
	rows = frappe.get_all(
		"Packaging Item Group",
		filters={"parent": "General Settings", "parenttype": "General Settings"},
		fields=["item_group"],
		order_by="idx asc",
	)

	groups: set[str] = set()
	for row in rows:
		if not row.item_group:
			continue
		groups.add(row.item_group)
		groups.update(get_descendants_of("Item Group", row.item_group))
	return groups


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
