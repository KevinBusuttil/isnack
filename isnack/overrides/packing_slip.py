"""Packing Slip weight calculation override.

The Item master stores three weight fields:

    custom_net_weight_per_unit  -- net weight of the goods
    custom_tare_weight_per_unit -- packaging (tare) weight
    weight_per_unit             -- kept in sync as net + tare (i.e. GROSS)
                                   by ``isnack.overrides.item.sync_weight_per_unit``

Stock ERPNext populates Packing Slip Item ``net_weight`` from the Item's
``weight_per_unit``, which here is the *gross* weight. That makes the package
Net Weight equal the Gross Weight. This override sources the per-item net
weight from ``custom_net_weight_per_unit`` and always derives the package
gross weight from ``weight_per_unit`` (net + tare).

Items in the Item Groups listed under General Settings → Packing are packaging
(pallets, cartons, wrap). Packaging shipped as its own line carries no goods,
so it adds nothing to Net Weight and its full weight to Gross Weight -- the
customs meaning of the two figures.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.stock.doctype.packing_slip.packing_slip import PackingSlip

from isnack.isnack.doctype.general_settings.general_settings import (
    get_packaging_item_groups,
)


class CustomPackingSlip(PackingSlip):
    def set_missing_values(self):
        if not self.from_case_no:
            self.from_case_no = self.get_recommended_case_no()

        for item in self.items:
            net_weight_per_unit, weight_per_unit, weight_uom = frappe.db.get_value(
                "Item",
                item.item_code,
                ["custom_net_weight_per_unit", "weight_per_unit", "weight_uom"],
            )
            # Fall back to the gross weight only when the Item has no net
            # weight recorded at all. `or` would also swallow an explicit 0,
            # which is exactly what a packaging item is entitled to have.
            if net_weight_per_unit in (None, ""):
                default_net = flt(weight_per_unit)
            else:
                default_net = flt(net_weight_per_unit)
            if default_net and not item.net_weight:
                item.net_weight = default_net
            if weight_uom and not item.weight_uom:
                item.weight_uom = weight_uom

    def calculate_net_total_pkg(self):
        self.net_weight_uom = self.items[0].weight_uom if self.items else None
        self.gross_weight_uom = self.net_weight_uom

        packaging_groups = get_packaging_item_groups()

        net_weight_pkg = 0
        gross_weight_pkg = 0
        for item in self.items:
            if item.weight_uom != self.net_weight_uom:
                frappe.throw(
                    _(
                        "Different UOM for items will lead to incorrect (Total) Net "
                        "Weight value. Make sure that Net Weight of each item is in "
                        "the same UOM."
                    )
                )

            gross_weight_per_unit, item_group = frappe.db.get_value(
                "Item", item.item_code, ["weight_per_unit", "item_group"]
            )

            if item_group in packaging_groups:
                # Zero the row as well as the total. The print formats show a
                # per-row Net Wt column that has to keep adding up to the Net
                # Weight printed at the foot of the slip.
                item.net_weight = 0

            net_weight_pkg += flt(item.net_weight) * flt(item.qty)
            gross_weight_pkg += flt(gross_weight_per_unit) * flt(item.qty)

        self.net_weight_pkg = round(net_weight_pkg, 2)
        self.gross_weight_pkg = round(gross_weight_pkg, 2)


def recalculate_stored_weights(names=None, commit=True):
    """Apply the packaging Net Weight exclusion to already-saved Packing Slips.

    ``calculate_net_total_pkg`` only runs while a document is being saved, so a
    slip saved before an Item Group was listed under General Settings → Packing
    keeps its old figures when reprinted. Amending is not a way out either:
    slips here are auto-created and submitted from ``Delivery Note``
    ``before_submit``, and ERPNext's ``validate_delivery_note`` refuses to
    validate a Packing Slip whose Delivery Note has left Draft. Writing the
    stored fields directly is the only route.

    Only Net Weight moves. Packaging still counts towards Gross Weight, so
    ``gross_weight_pkg`` is deliberately left alone.

    Safe to re-run -- slips already correct are skipped -- so it is also the
    way to apply a later change to the configured groups::

        bench --site <site> execute \\
            isnack.overrides.packing_slip.recalculate_stored_weights

    Returns the names of the slips that changed.
    """
    packaging_groups = get_packaging_item_groups()
    if not packaging_groups:
        return []

    if isinstance(names, str):
        names = [names]

    filters = {"docstatus": ["<", 2]}
    if names:
        filters["name"] = ["in", names]

    item_groups: dict[str, str] = {}
    changed = []

    for slip in frappe.get_all("Packing Slip", filters=filters, pluck="name"):
        rows = frappe.get_all(
            "Packing Slip Item",
            filters={"parent": slip, "parenttype": "Packing Slip"},
            fields=["name", "item_code", "qty", "net_weight"],
            order_by="idx asc",
        )

        net_weight_pkg = 0
        to_zero = []
        for row in rows:
            if row.item_code not in item_groups:
                item_groups[row.item_code] = frappe.db.get_value(
                    "Item", row.item_code, "item_group"
                )

            net_weight = flt(row.net_weight)
            if item_groups[row.item_code] in packaging_groups and net_weight:
                net_weight = 0
                to_zero.append(row.name)

            net_weight_pkg += net_weight * flt(row.qty)

        net_weight_pkg = round(net_weight_pkg, 2)
        stored = flt(frappe.db.get_value("Packing Slip", slip, "net_weight_pkg"))
        if not to_zero and net_weight_pkg == stored:
            continue

        # update_modified=False: these are submitted documents being corrected,
        # not edited, and the timestamp should keep pointing at the real edit.
        for row_name in to_zero:
            frappe.db.set_value(
                "Packing Slip Item", row_name, "net_weight", 0, update_modified=False
            )
        frappe.db.set_value(
            "Packing Slip", slip, "net_weight_pkg", net_weight_pkg, update_modified=False
        )
        changed.append(slip)

    if commit:
        frappe.db.commit()

    return changed
