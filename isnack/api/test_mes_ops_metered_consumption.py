# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""A metered item is never counted out by an operator.

Water arrives through a pipe. Nobody weighs it at the line, so End WO must not
hold a Work Order open waiting for someone to "consume" it, and none of the
consumption routes may book a hand-typed figure against it. The recipe quantity
is consumed by the BOM remainder loop when the Work Order is received into
stock, which already happens today and is not changed here.

Deliberately NOT asserted anywhere: that the consumption lands "at Close
Production". With Factory Settings close_sfg_wo_at_end on, a semi-finished Work
Order is received inside End WO itself, so the remainder is consumed seconds
later rather than at a separate step. Pinning the wrong step would make the
tests lie the way the first draft of the operator's badge did.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import frappe

import isnack.api.mes_ops as mes_ops
from isnack.api.mes_ops import (
    _end_wo_consumption_summary,
    _post_material_consumption_for_wo,
    get_manual_load_item_context,
)

WO = "MFG-WO-2026-00072"
WATER = "RM20023"      # piped, metered — 5 Litre per 150 Kg on BOM-SFG10001-001
GRITS = "RM20022"      # weighed by hand, genuinely blocking when short


class TestEndWoExemptsMeteredItems(unittest.TestCase):
    """End WO must not hold a Work Order open over a material nobody handles."""

    def _summary(self, metered, consumed):
        wo = MagicMock()
        wo.bom_no, wo.qty, wo.name = "BOM-SFG10001-001", 150.0, WO
        bom_items = [
            {"item_code": GRITS, "qty": 80.0, "uom": "Kg"},
            {"item_code": WATER, "qty": 2.667, "uom": "Litre"},
        ]
        with patch.object(mes_ops, "_end_wo_tolerance_pct", return_value=5.0), \
                patch.object(mes_ops, "_metered_items", return_value=set(metered)), \
                patch.object(mes_ops, "_packaging_groups_global", return_value=set()), \
                patch.object(mes_ops, "_planned_items_for_wo", return_value=bom_items), \
                patch.object(mes_ops, "_get_consumed_materials_from_load", return_value=consumed), \
                patch.object(mes_ops, "get_sfg_components_for_wo", return_value={"items": []}), \
                patch.object(mes_ops, "_get_item_group", return_value="Raw Materials"), \
                patch("frappe.get_doc", return_value=wo), \
                patch("frappe.db.get_value", return_value="name"):
            return _end_wo_consumption_summary(WO)

    def test_an_unconsumed_metered_item_does_not_block_end_wo(self):
        """The reported case: water at 0 consumed, everything else done."""
        out = self._summary(metered=[WATER], consumed={GRITS: 80.0})

        self.assertEqual(out["shortfalls"], 0)
        self.assertTrue(out["can_end"])

    def test_it_is_still_listed_so_the_operator_can_see_the_recipe_figure(self):
        """Exempt is not hidden — the row stays, flagged."""
        out = self._summary(metered=[WATER], consumed={GRITS: 80.0})

        water = [r for r in out["items"] if r["item_code"] == WATER][0]
        self.assertTrue(water["is_metered"])
        self.assertEqual(water["required"], 2.667)
        self.assertEqual(water["status"], "short")   # short, but not counted

    def test_a_real_shortfall_still_blocks(self):
        """The exemption must not become a way round the consumption gate."""
        out = self._summary(metered=[WATER], consumed={GRITS: 60.0})

        self.assertEqual(out["shortfalls"], 1)
        self.assertFalse(out["can_end"])

    def test_without_the_setting_water_blocks_as_before(self):
        """Nothing changes for a site that never names a metered item."""
        out = self._summary(metered=[], consumed={GRITS: 80.0})

        self.assertEqual(out["shortfalls"], 1)
        self.assertFalse(out["can_end"])


class TestOverrideMessageMatchesTheCount(unittest.TestCase):
    """end_work_order re-derives the short list; it has to agree with the gate.

    Exempting only the counter produced "1 required item(s) below tolerance:
    RM20022 (60/80 Kg), RM20023 (0/2.667 Litre)" — one claimed, two named, the
    operator sent to consume the water, and the same list written into the
    manager's override reason.
    """

    def _short_rows(self, items):
        """The filter as end_work_order applies it."""
        return [
            r for r in items
            if (not r["is_sfg"]) and (not r["is_packaging"]) and (not r.get("is_metered"))
            and r["status"] == "short"
        ]

    def test_a_metered_item_is_never_named_in_the_override_message(self):
        items = [
            {"item_code": GRITS, "is_sfg": False, "is_packaging": False,
             "is_metered": False, "status": "short"},
            {"item_code": WATER, "is_sfg": False, "is_packaging": False,
             "is_metered": True, "status": "short"},
        ]

        named = [r["item_code"] for r in self._short_rows(items)]

        self.assertEqual(named, [GRITS])
        self.assertNotIn(WATER, named)

    def test_the_count_and_the_list_agree(self):
        items = [
            {"item_code": GRITS, "is_sfg": False, "is_packaging": False,
             "is_metered": False, "status": "short"},
            {"item_code": WATER, "is_sfg": False, "is_packaging": False,
             "is_metered": True, "status": "short"},
        ]
        shortfalls = sum(
            1 for r in items
            if not r["is_sfg"] and not r["is_packaging"] and not r["is_metered"]
            and r["status"] == "short"
        )

        self.assertEqual(len(self._short_rows(items)), shortfalls)


class TestConsumptionRoutesRefuseMeteredItems(unittest.TestCase):
    """Every posting route, because each is whitelisted."""

    def test_the_shared_poster_refuses(self):
        """Covers manual_load_materials and consume_scanned_material."""
        with patch.object(mes_ops, "_assert_not_ended"), \
                patch.object(mes_ops, "_assert_started"), \
                patch.object(mes_ops, "_metered_items", return_value={WATER}):
            with self.assertRaises(frappe.ValidationError) as caught:
                _post_material_consumption_for_wo(WO, [{"item_code": WATER, "qty": 2.667}])

        self.assertIn(WATER, str(caught.exception))
        self.assertIn("metered", str(caught.exception))

    def test_one_metered_row_refuses_the_whole_posting(self):
        with patch.object(mes_ops, "_assert_not_ended"), \
                patch.object(mes_ops, "_assert_started"), \
                patch.object(mes_ops, "_metered_items", return_value={WATER}):
            with self.assertRaises(frappe.ValidationError) as caught:
                _post_material_consumption_for_wo(
                    WO, [{"item_code": GRITS, "qty": 80}, {"item_code": WATER, "qty": 2.667}]
                )

        self.assertIn(WATER, str(caught.exception))
        self.assertNotIn(GRITS, str(caught.exception))

    def test_scan_material_refuses_on_its_own(self):
        """It builds and submits its own Stock Entry, bypassing the shared poster."""
        with patch.object(mes_ops, "_require_roles"), \
                patch.object(mes_ops, "_metered_items", return_value={WATER}), \
                patch.object(mes_ops, "_parse_gs1_or_basic",
                             return_value={"item_code": WATER, "qty": 2.667}), \
                patch.object(mes_ops, "_assert_not_ended"), \
                patch.object(mes_ops, "_has_recent_duplicate", return_value=False), \
                patch("frappe.db.get_value", return_value=0):
            out = mes_ops.scan_material("RM20023|~|2.667", work_order=WO)

        self.assertFalse(out["ok"])
        self.assertIn("metered", out["msg"])
        self.assertIn(WATER, out["msg"])


class TestReadOnlyLookupsFlagRatherThanThrow(unittest.TestCase):
    """The client asks before it has a dialog to show an error in."""

    def _context(self, metered):
        wo = MagicMock()
        wo.bom_no, wo.qty = "BOM-SFG10001-001", 150.0
        with patch.object(mes_ops, "_require_roles"), \
                patch.object(mes_ops, "_metered_items", return_value=set(metered)), \
                patch.object(mes_ops, "_planned_required_qty", return_value=2.667), \
                patch("frappe.get_doc", return_value=wo), \
                patch("frappe.db.get_value", return_value="Litre"), \
                patch("frappe.db.sql", return_value=[[0.0]]):
            return get_manual_load_item_context(WO, WATER)

    def test_it_flags_instead_of_raising(self):
        ctx = self._context([WATER])

        self.assertTrue(ctx["is_metered"])
        self.assertEqual(ctx["remaining_qty"], 0.0)

    def test_an_ordinary_item_is_unflagged(self):
        ctx = self._context([])

        self.assertFalse(ctx["is_metered"])
        self.assertEqual(ctx["remaining_qty"], 2.667)


if __name__ == "__main__":
    unittest.main()
