# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for the declared-output clamp on the Manufacture Stock Entry.

A Work Order split out of a Production Plan carries a repeating quantity
(320/3 = 106.666666667). Both routes that book its output — End WO in
structural mode and Close Production's proportional split — hand the quantity
through Frappe Float handling, which rounds to the system float precision, so
106.667 arrives for a 106.666666667 Work Order. With
``overproduction_percentage_for_work_order = 0`` ERPNext rejects that outright:
"For quantity 106.667 should not be greater than allowed quantity
106.666666667" (``StockEntry.validate_finished_goods``, version-15).

These tests pin the clamp that absorbs the rounding artefact while still
refusing a genuine over-declaration.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

import isnack.api.mes_ops as mes_ops
from isnack.api.mes_ops import (
    _clamp_good_qty_to_allowance,
    _close_single_wo,
    _wo_allowed_output_qty,
)

# 320 kg split across three Work Orders.
SPLIT_WO_QTY = 106.666666667
# What a Frappe Float field returns for that quantity at precision 3.
ROUNDED_UP_QTY = 106.667
# What the clamp must return: the largest quantity that is simultaneously at or
# below the Work Order ceiling AND equal to its own value at precision 3.
FLOORED_WO_QTY = 106.666


class FakeStockEntry:
    """Minimal stand-in for a Stock Entry doc that records appended rows."""

    def __init__(self):
        self.items = []
        self.flags = MagicMock()
        self.name = "MAT-STE-NEW"

    def append(self, table, row):
        self.items.append(row)

    def insert(self):
        pass

    def submit(self):
        pass


def _wo(qty=SPLIT_WO_QTY):
    wo = MagicMock()
    wo.qty = qty
    wo.company = "Test Co"
    wo.bom_no = "BOM-SFG10001-001"
    wo.use_multi_level_bom = 0
    wo.actual_end_date = None
    wo.wip_warehouse = "EXT1-WIP - ISN"
    wo.fg_warehouse = "Semi-finished - ISN"
    wo.production_item = "SFG10001"
    return wo


def _single_value(allowance=0, material_consumption=1):
    """frappe.db.get_single_value stub: overproduction allowance, the
    material-consumption precondition, and the default warehouse."""

    def _get(doctype, fieldname, *a, **k):
        if doctype == "Manufacturing Settings":
            if fieldname == "material_consumption":
                return material_consumption
            return allowance
        return "Semi-finished - ISN"

    return _get


class TestWoAllowedOutputQty(unittest.TestCase):
    def test_zero_allowance_is_the_work_order_qty_exactly(self):
        """The ceiling must compare equal, not merely close, to ERPNext's own —
        both are `wo_qty + ((pct / 100) * wo_qty)` on the same float."""
        with patch.object(mes_ops.frappe.db, "get_single_value",
                          side_effect=_single_value(0)):
            allowed = _wo_allowed_output_qty(SPLIT_WO_QTY)

        self.assertEqual(allowed, SPLIT_WO_QTY)
        self.assertFalse(allowed > SPLIT_WO_QTY)

    def test_allowance_percentage_raises_the_ceiling(self):
        with patch.object(mes_ops.frappe.db, "get_single_value",
                          side_effect=_single_value(10)):
            self.assertAlmostEqual(_wo_allowed_output_qty(100.0), 110.0, places=9)

    def test_unset_allowance_is_treated_as_zero(self):
        with patch.object(mes_ops.frappe.db, "get_single_value",
                          side_effect=_single_value(None)):
            self.assertEqual(_wo_allowed_output_qty(100.0), 100.0)


class TestClampGoodQtyToAllowance(unittest.TestCase):
    def _clamp(self, good, wo_qty=SPLIT_WO_QTY, allowance=0, precision=3):
        with patch.object(mes_ops.frappe.db, "get_single_value",
                          side_effect=_single_value(allowance)), \
             patch.object(mes_ops.frappe, "get_precision", return_value=precision):
            return _clamp_good_qty_to_allowance("MFG-WO-2026-00055", wo_qty, good)

    def test_rounded_up_prefill_is_snapped_below_the_ceiling(self):
        """The reported failure: 106.667 submitted for a 106.666666667 WO."""
        self.assertEqual(self._clamp(ROUNDED_UP_QTY), FLOORED_WO_QTY)

    def test_clamped_value_passes_BOTH_erpnext_checks(self):
        """The two checks pull in opposite directions and only a quantised value
        satisfies both — this is what makes the raw ceiling wrong."""
        clamped = self._clamp(ROUNDED_UP_QTY)

        # 1. validate_finished_goods: `if fg_completed_qty > allowed_qty: throw`
        allowed_qty = SPLIT_WO_QTY + ((0 / 100) * SPLIT_WO_QTY)
        self.assertFalse(clamped > allowed_qty)

        # 2. validate_fg_completed_qty: `if fg_completed_qty != flt(total, 3)`
        #    where total = flt(sum(finished-item qtys), 3). _close_single_wo puts
        #    the same value on both, so the check reduces to self-consistency
        #    under rounding — which the raw 106.666666667 fails (it totals to
        #    106.667) and 106.666 passes.
        self.assertEqual(clamped, round(clamped, 3))
        self.assertNotEqual(SPLIT_WO_QTY, round(SPLIT_WO_QTY, 3))

    def test_quantity_under_the_ceiling_is_untouched(self):
        self.assertEqual(self._clamp(100.0), 100.0)

    def test_fractional_split_under_the_ceiling_is_still_quantised(self):
        """Close Production splitting 100 over three 50 Kg WOs yields
        33.333333333333336, which never reaches the over-ceiling branch — it is
        the early return that has to quantise it, or validate_fg_completed_qty
        rejects the entry."""
        self.assertEqual(self._clamp(100 / 3, wo_qty=50.0), 33.333)

    def test_quantity_exactly_at_the_ceiling_is_quantised(self):
        self.assertEqual(self._clamp(SPLIT_WO_QTY), FLOORED_WO_QTY)

    def test_zero_is_left_for_the_callers_own_validation(self):
        """`end_work_order` rejects a zero good qty with its own message; the
        clamp must not pre-empt that."""
        self.assertEqual(self._clamp(0.0), 0.0)

    def test_real_over_declaration_is_refused(self):
        """Beyond one precision unit is a deliberate over-declaration, not a
        rounding artefact — it must not be silently swallowed."""
        def fake_throw(*args, **kwargs):
            raise RuntimeError(args[0] if args else "throw")

        with patch.object(mes_ops.frappe, "throw", side_effect=fake_throw):
            with self.assertRaises(RuntimeError) as ctx:
                self._clamp(120.0)

        msg = str(ctx.exception)
        self.assertIn("MFG-WO-2026-00055", msg)
        self.assertIn("Overproduction Percentage For Work Order", msg)

    def test_over_declaration_allowed_when_the_setting_permits_it(self):
        self.assertEqual(self._clamp(105.0, wo_qty=100.0, allowance=10), 105.0)

    def test_clamp_follows_the_configured_qty_precision(self):
        """At precision 2 the rounding step is 0.01, so a 0.005 excess is still
        an artefact; at precision 3 the same excess would be a real overshoot
        only above 0.001."""
        self.assertEqual(self._clamp(100.005, wo_qty=100.0, precision=2), 100.0)


class TestCloseSingleWoClampsDeclaredOutput(unittest.TestCase):
    def _close(self, good, reject=0.0):
        """Run _close_single_wo against a fractional-qty WO and return the
        Manufacture Stock Entry it built plus the qty the BOM was scaled to."""
        se = FakeStockEntry()
        bom_scaled_to = {}

        def fake_bom_items(bom_no, qty, exploded=True):
            bom_scaled_to["qty"] = qty
            return []

        def db_get_value(doctype, name, field, *a, **k):
            if field == "stock_uom":
                return "Kg"
            if field == "has_batch_no":
                return 0
            return None

        with patch.object(mes_ops.frappe, "get_doc", return_value=_wo()), \
             patch.object(mes_ops, "_submitted_mtfm_qty", return_value=SPLIT_WO_QTY), \
             patch.object(mes_ops, "_submitted_manufacture_qty", return_value=0.0), \
             patch.object(mes_ops, "_default_line_target", return_value="Semi-finished - ISN"), \
             patch.object(mes_ops, "_default_line_wip", return_value="EXT1-WIP - ISN"), \
             patch.object(mes_ops, "_default_line_staging", return_value="EXT1-STAGING - ISN"), \
             patch.object(mes_ops, "_default_line_scrap", return_value="Scrap - ISN"), \
             patch.object(mes_ops, "_sweep_surplus_to_wip", return_value=[]), \
             patch.object(mes_ops, "_get_consumed_materials_from_load", return_value={}), \
             patch.object(mes_ops, "_get_bom_items_for_quantity", side_effect=fake_bom_items), \
             patch.object(mes_ops, "get_sfg_components_for_wo", return_value={"items": []}), \
             patch.object(mes_ops, "_default_sfg_source", return_value="Semi-finished - ISN"), \
             patch.object(mes_ops, "_packaging_groups_global", return_value=set()), \
             patch.object(mes_ops, "_apply_pre_consumed_cost_to_finished_item"), \
             patch.object(mes_ops.frappe, "get_precision", return_value=3), \
             patch.object(mes_ops.frappe.utils, "now_datetime", return_value="2026-08-06 10:00:00"), \
             patch.object(mes_ops.frappe.db, "get_value", side_effect=db_get_value), \
             patch.object(mes_ops.frappe.db, "get_single_value", side_effect=_single_value(0)), \
             patch.object(mes_ops.frappe.db, "set_value"), \
             patch.object(mes_ops.frappe, "new_doc", return_value=se):
            _close_single_wo({"name": "MFG-WO-2026-00055"},
                             {"good": good, "reject": reject, "packaging": []}, None)

        return se, bom_scaled_to.get("qty")

    def test_rounded_prefill_no_longer_exceeds_the_work_order(self):
        se, _ = self._close(ROUNDED_UP_QTY)

        self.assertEqual(se.fg_completed_qty, FLOORED_WO_QTY)
        finished = [r for r in se.items if r.get("is_finished_item")]
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0]["qty"], FLOORED_WO_QTY)

    def test_fg_row_and_for_quantity_agree_under_rounding(self):
        """validate_fg_completed_qty compares fg_completed_qty against
        flt(sum(finished-item qtys), 3). They must not diverge, or ERPNext
        throws "quantity ... and For Quantity ... cannot be different"."""
        se, _ = self._close(ROUNDED_UP_QTY)

        total = round(sum(r["qty"] for r in se.items if r.get("is_finished_item")), 3)
        self.assertEqual(se.fg_completed_qty, total)

    def test_bom_is_scaled_to_the_clamped_output(self):
        """Consumption must follow the quantity actually received, not the
        rounded-up figure the operator submitted."""
        _, scaled_to = self._close(ROUNDED_UP_QTY)

        self.assertEqual(scaled_to, FLOORED_WO_QTY)

    def test_rejects_still_scale_the_bom_on_top_of_the_clamped_good_qty(self):
        _, scaled_to = self._close(ROUNDED_UP_QTY, reject=2.0)

        self.assertAlmostEqual(scaled_to, FLOORED_WO_QTY + 2.0, places=9)


if __name__ == "__main__":
    unittest.main()
