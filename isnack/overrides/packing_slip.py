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
