# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The finished goods: the items of the Finished Goods item group, or of a
group under it (2026-11).

A tasting's Batch No is one's batch, and the Batch Explorer's and the Quality
Explorer's Batch pickers offer only their batches.
"""

import frappe

FINISHED_GOODS = "Finished Goods"


def finished_good_groups() -> list[str]:
    """The Finished Goods item group and the groups under it; none when there
    is no such group."""
    group = frappe.db.get_value("Item Group", FINISHED_GOODS, ["lft", "rgt"], as_dict=True)
    if not group:
        return []
    return frappe.get_all("Item Group", filters={"lft": [">=", group.lft], "rgt": ["<=", group.rgt]}, pluck="name")


def finished_goods() -> list[str]:
    """The items of the Finished Goods item group, or of a group under it."""
    groups = finished_good_groups()
    if not groups:
        return []
    return frappe.get_all("Item", filters={"item_group": ["in", groups]}, pluck="name")
