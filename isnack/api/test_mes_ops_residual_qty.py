# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for sub-tick material residuals on the Manufacture Stock Entry.

The failure these pin: MFG-WO-2026-00059 produced 10 Kg of SFG10001 from a BOM
whose water line is 1/30 per Kg. The requirement is 0.333333333 L; the only
quantity the Stock Ledger can hold is 0.333, which is what the operator
consumed. The 0.000333333 L remainder cleared ISNACK's QTY_EPSILON (1e-4) and
became a row on the Manufacture entry, where ERPNext rejected it:

    Row 2: Qty in Stock UOM can not be zero.        [title: Zero quantity]
    erpnext/stock/doctype/stock_entry/stock_entry.py set_transfer_qty()

The remainder is by construction `required - round(required, P)`, so it is
bounded by half a tick and can NEVER be posted. QTY_EPSILON being five times
smaller than that boundary is what let it through — so the gate has to be one
unit at the posting precision, not a hardcoded constant.
"""

import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import frappe

import isnack.api.mes_ops as mes_ops
from isnack.api.mes_ops import _close_single_wo
from isnack.utils.qty import postable_qty, qty_precision, qty_tick, truncate_qty

# MFG-WO-2026-00059, verified against the production export.
WO_QTY = 10.0
WATER_REQUIRED = 0.333333333
WATER_CONSUMED = 0.333
CORN_REQUIRED = 10.0
CORN_CONSUMED = 10.0


class FakeStockEntry:
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


def _wo(qty=WO_QTY):
    wo = MagicMock()
    wo.qty = qty
    wo.company = "Isnack"
    wo.bom_no = "BOM-SFG10001-001"
    wo.use_multi_level_bom = 0
    wo.actual_end_date = None
    wo.wip_warehouse = "EXT1-WIP - ISN"
    wo.fg_warehouse = "Semi-finished - ISN"
    wo.production_item = "SFG10001"
    return wo


def _single_value(material_consumption=1):
    def _get(doctype, fieldname, *a, **k):
        if doctype == "Manufacturing Settings":
            if fieldname == "material_consumption":
                return material_consumption
            return 0
        return "Semi-finished - ISN"

    return _get


class TestQtyHelpers(unittest.TestCase):
    """The quantum is one unit at the posting precision, read from the
    framework — not a constant."""

    def _at(self, precision):
        return patch.object(frappe, "get_precision", return_value=precision)

    def test_tick_follows_the_site_precision(self):
        with self._at(3):
            self.assertEqual(qty_precision(), 3)
            self.assertAlmostEqual(qty_tick(), 0.001, places=12)
        with self._at(6):
            self.assertAlmostEqual(qty_tick(), 0.000001, places=12)

    def test_precision_of_zero_falls_back_to_three(self):
        """flt(x, 0) would integer-round every quantity in the app."""
        with self._at(0):
            self.assertEqual(qty_precision(), 3)

    def test_the_reported_residual_is_not_postable(self):
        with self._at(3):
            self.assertEqual(truncate_qty(WATER_REQUIRED - WATER_CONSUMED), 0.0)
            self.assertEqual(postable_qty(WATER_REQUIRED - WATER_CONSUMED), 0.0)

    def test_qty_epsilon_is_smaller_than_the_rounding_boundary(self):
        """The root cause, pinned: any residual in (QTY_EPSILON, half a tick]
        passed the old gate and then rounded to zero for ERPNext."""
        with self._at(3):
            self.assertLess(mes_ops.QTY_EPSILON, qty_tick() / 2)
            trap = 0.0003
            self.assertGreater(abs(trap), mes_ops.QTY_EPSILON)   # old gate: emit
            self.assertEqual(truncate_qty(trap), 0.0)            # new gate: drop

    def test_truncate_never_inflates_a_residual(self):
        with self._at(3):
            self.assertEqual(truncate_qty(0.0015), 0.001)
            self.assertEqual(truncate_qty(1.9999), 1.999)

    def test_truncate_moves_toward_zero_for_negatives(self):
        """Over-consumption magnitude must never be reported larger than it
        was, so this truncates rather than floors."""
        with self._at(3):
            self.assertEqual(truncate_qty(-0.0015), -0.001)
            self.assertEqual(truncate_qty(-0.0004), 0.0)

    def test_postable_qty_preserves_sign(self):
        """It is a postability test, not a safety test — callers keep their own
        sign check, because a negative quantity IS postable."""
        with self._at(3):
            self.assertEqual(postable_qty(-5.0), -5.0)
            self.assertTrue(postable_qty(-5.0))


class TestCloseSingleWoResiduals(unittest.TestCase):
    def _close(self, bom_items, consumed, good=WO_QTY, reject=0.0,
               packaging=None, material_consumption=1, consumed_by_batch=None):
        se = FakeStockEntry()
        logged = []

        def db_get_value(doctype, name, field, *a, **k):
            if field == "stock_uom":
                return "Kg"
            if field == "has_batch_no":
                return 0
            return None

        patches = [
            patch.object(mes_ops.frappe, "get_doc", return_value=_wo()),
            patch.object(mes_ops, "_submitted_mtfm_qty", return_value=WO_QTY),
            patch.object(mes_ops, "_submitted_manufacture_qty", return_value=0.0),
            patch.object(mes_ops, "_default_line_target", return_value="Semi-finished - ISN"),
            patch.object(mes_ops, "_default_line_wip", return_value="EXT1-WIP - ISN"),
            patch.object(mes_ops, "_default_line_staging", return_value="EXT1-STAGING - ISN"),
            patch.object(mes_ops, "_default_line_scrap", return_value="Scrap - ISN"),
            patch.object(mes_ops, "_sweep_surplus_to_wip", return_value=[]),
            patch.object(mes_ops, "_get_consumed_materials_from_load", return_value=consumed),
            patch.object(mes_ops, "_get_bom_items_for_quantity", return_value=bom_items),
            patch.object(mes_ops, "get_sfg_components_for_wo", return_value={"items": []}),
            patch.object(mes_ops, "_default_sfg_source", return_value="Semi-finished - ISN"),
            patch.object(mes_ops, "_packaging_groups_global", return_value={"packaging"}),
            patch.object(mes_ops, "_get_item_group", return_value="Raw Materials"),
            patch.object(mes_ops, "_consumed_qty_by_batch",
                         return_value=consumed_by_batch or {}),
            patch.object(mes_ops, "_apply_pre_consumed_cost_to_finished_item"),
            patch.object(mes_ops.frappe, "get_precision", return_value=3),
            patch.object(mes_ops.frappe, "log_error", side_effect=lambda **kw: logged.append(kw)),
            patch.object(mes_ops.frappe.utils, "now_datetime", return_value="2026-08-07 12:00:00"),
            patch.object(mes_ops.frappe.db, "get_value", side_effect=db_get_value),
            patch.object(mes_ops.frappe.db, "get_single_value",
                         side_effect=_single_value(material_consumption)),
            patch.object(mes_ops.frappe.db, "set_value"),
            patch.object(mes_ops.frappe, "new_doc", return_value=se),
        ]
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            _close_single_wo(
                {"name": "MFG-WO-2026-00059"},
                {"good": good, "reject": reject, "packaging": packaging or []},
                None,
            )

        return se, logged

    @staticmethod
    def _materials(se):
        return [r for r in se.items if not r.get("is_finished_item")
                and not r.get("is_scrap_item")]

    def _wo59_bom(self):
        return [
            {"item_code": "RM20022", "qty": CORN_REQUIRED, "uom": "Kg"},
            {"item_code": "RM20023", "qty": WATER_REQUIRED, "uom": "Litre"},
        ]

    def test_wo59_closes_with_no_material_rows(self):
        """The reported outage. Corn nets to exactly zero and water leaves a
        sub-tick remainder, so the entry is finished-item only."""
        se, _ = self._close(
            self._wo59_bom(),
            {"RM20022": CORN_CONSUMED, "RM20023": WATER_CONSUMED},
        )

        self.assertEqual(self._materials(se), [])
        self.assertEqual(len(se.items), 1)
        self.assertTrue(se.items[0]["is_finished_item"])

    def test_no_row_can_ever_round_to_zero(self):
        """The property that makes the class of bug impossible, not just this
        instance: every emitted row survives ERPNext's transfer_qty check."""
        se, _ = self._close(
            [
                {"item_code": "A", "qty": 5.0004, "uom": "Kg"},        # sub-tick
                {"item_code": "B", "qty": 7.0015, "uom": "Kg"},        # postable
                {"item_code": "C", "qty": 2.00049, "uom": "Kg"},       # sub-tick
            ],
            {"A": 5.0, "B": 7.0, "C": 2.0},
        )

        for row in self._materials(se):
            self.assertNotEqual(round(row["qty"], 3), 0.0, msg=f"unpostable row {row}")
        self.assertEqual([r["item_code"] for r in self._materials(se)], ["B"])
        self.assertEqual(self._materials(se)[0]["qty"], 0.001)

    def test_a_genuine_shortfall_is_still_consumed(self):
        """Quantising must not swallow real material."""
        se, _ = self._close(
            [{"item_code": "RM20022", "qty": 10.0, "uom": "Kg"}],
            {"RM20022": 6.0},
        )

        rows = self._materials(se)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["qty"], 4.0)
        self.assertEqual(rows[0]["s_warehouse"], "EXT1-WIP - ISN")

    def test_over_consumption_is_still_logged_at_its_raw_magnitude(self):
        """WO-45/49 shape: the operator loaded the 0.001 L leftover, so the
        remainder went negative. That is a real variance and must be reported
        at full magnitude, not quantised."""
        se, logged = self._close(
            [{"item_code": "RM20023", "qty": WATER_REQUIRED, "uom": "Litre"}],
            {"RM20023": 0.334},
        )

        self.assertEqual(self._materials(se), [])
        over = [m for m in logged if m.get("title") == "Material Over-Consumption"]
        self.assertEqual(len(over), 1)
        self.assertIn("0.0007", over[0]["message"])  # 0.000667, not 0.000 or 0.001

    def test_sub_tick_over_consumption_is_not_logged_as_variance(self):
        """Below QTY_EPSILON is float noise, and stays unreported as it is
        today — the quantisation must not change which side of that line a
        remainder falls on."""
        _, logged = self._close(
            [{"item_code": "RM20023", "qty": 1.0, "uom": "Litre"}],
            {"RM20023": 1.00005},
        )

        self.assertEqual([m for m in logged if m.get("title") == "Material Over-Consumption"], [])

    def test_packaging_residual_is_quantised_too(self):
        """The packaging loop builds rows the same way and had the same gate:
        21.0003 entered against 21.0 already consumed leaves a sub-tick
        remainder that must not become a row."""
        se, _ = self._close(
            [],
            {},
            packaging=[{"item_code": "PM40011", "qty": 21.0003, "batch_no": None}],
            consumed_by_batch={"": 21.0},
        )

        self.assertEqual([r for r in self._materials(se) if r["item_code"] == "PM40011"], [])

    def test_postable_packaging_remainder_is_still_emitted(self):
        se, _ = self._close(
            [],
            {},
            packaging=[{"item_code": "PM40011", "qty": 21.0, "batch_no": None}],
            consumed_by_batch={"": 5.0},
        )

        rows = [r for r in self._materials(se) if r["item_code"] == "PM40011"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["qty"], 16.0)

    def test_missing_material_consumption_setting_is_named(self):
        """An all-consumed close produces a finished-item-only entry, which
        erpnext's validate_raw_materials_exists rejects unless the setting is
        on. Surface the setting rather than its generic message."""
        def fake_throw(*args, **kwargs):
            raise RuntimeError(args[0] if args else "throw")

        with patch.object(mes_ops.frappe, "throw", side_effect=fake_throw):
            with self.assertRaises(RuntimeError) as ctx:
                self._close(
                    self._wo59_bom(),
                    {"RM20022": CORN_CONSUMED, "RM20023": WATER_CONSUMED},
                    material_consumption=0,
                )

        self.assertIn("Material Consumption", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
