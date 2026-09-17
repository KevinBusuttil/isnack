# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The leftover tick of a metered material is consumed at close, not stranded.

A BOM ratio that is not representable at the posting precision always leaves a
sub-tick remainder: water is 1/30 per Kg of CORN MIX 1, so 10 Kg asks for
0.333333333 L and the Stock Ledger can only hold 0.333. Every item truncates
that remainder away (see test_mes_ops_residual_qty), leaving it in WIP for the
operator to carry back or load into the next order.

A metered item has no operator. Nobody weighs out piped water and nobody carries
it back — which is exactly why it is excluded from the consume dialog and from
End Shift Return — so its tick has no way out of WIP, and the production site
has the hand-written Stock Entries (MAT-STE-2026-00254, -00275) to prove people
were clearing it manually. The transfer at Start rounds the same requirement UP,
so the material is genuinely there.

So a metered remainder rounds up instead, but only to the extent it is covered
twice over:

* by what this Work Order itself brought into WIP, less what it has consumed —
  never another order's material; and
* by what the warehouse actually holds, because WIP is a pool shared across the
  line and this site runs with Allow Negative Stock off, so a row beyond the
  ledger balance would block the close outright.

Anything uncertain falls back to the truncation every other item gets.
"""

import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import frappe

import isnack.api.mes_ops as mes_ops
from isnack.api.mes_ops import _metered_close_qty, _metered_headroom, _wip_actual_qty

WATER = "RM20023"          # metered: piped, never handled
CORN = "RM20022"           # handled like anything else
WO_QTY = 10.0
WATER_REQUIRED = 0.333333333       # 10 Kg at 1/30 per Kg
WATER_TRANSFERRED = 0.334          # Start rounds the requirement up
WIP = "EXT1-WIP - ISN"
SFG_WH = "Semi-finished - ISN"


class FakeStockEntry:
    def __init__(self):
        self.items = []
        self.flags = MagicMock()
        self.name = "MAT-STE-NEW"

    def append(self, _table, row):
        self.items.append(row)

    def insert(self):
        pass

    def submit(self):
        pass


def _wo():
    wo = MagicMock()
    wo.name = "MFG-WO-2026-00063"
    wo.qty = WO_QTY
    wo.company = "Isnack"
    wo.bom_no = "BOM-SFG10001-001"
    wo.use_multi_level_bom = 0
    wo.actual_end_date = None
    wo.wip_warehouse = WIP
    wo.fg_warehouse = SFG_WH
    wo.production_item = "SFG10001"
    return wo


class MeteredCloseHarness(unittest.TestCase):
    """Drives the two remainder loops — Close Production and End WO — through
    the same fixture, because they have to agree on every case below."""

    def _patches(self, bom_items, consumed, metered, inflow, on_hand,
                 sfg_codes, se, logged):
        def db_get_value(doctype, name, field, *a, **k):
            if field == "stock_uom":
                return "Kg"
            if field == "has_batch_no":
                return 0
            return None

        def single_value(doctype, fieldname, *a, **k):
            return 0 if doctype == "Manufacturing Settings" else SFG_WH

        return [
            patch.object(mes_ops.frappe, "get_doc", return_value=_wo()),
            patch.object(mes_ops, "_require_roles"),
            patch.object(mes_ops, "_submitted_mtfm_qty", return_value=WO_QTY),
            patch.object(mes_ops, "_submitted_manufacture_qty", return_value=0.0),
            patch.object(mes_ops, "_default_line_target", return_value=SFG_WH),
            patch.object(mes_ops, "_default_line_wip", return_value=WIP),
            patch.object(mes_ops, "_default_line_staging", return_value="EXT1-STAGING - ISN"),
            patch.object(mes_ops, "_default_line_scrap", return_value="Scrap - ISN"),
            patch.object(mes_ops, "_sweep_surplus_to_wip", return_value=[]),
            patch.object(mes_ops, "_get_consumed_materials_from_load", return_value=consumed),
            patch.object(mes_ops, "_planned_items_for_wo", return_value=bom_items),
            patch.object(mes_ops, "_get_bom_items_for_quantity", return_value=bom_items),
            patch.object(mes_ops, "get_sfg_components_for_wo",
                         return_value={"items": [{"item_code": c} for c in sfg_codes]}),
            patch.object(mes_ops, "_default_sfg_source", return_value=SFG_WH),
            patch.object(mes_ops, "_packaging_groups_global", return_value={"packaging"}),
            patch.object(mes_ops, "_get_item_group", return_value="Raw Materials"),
            patch.object(mes_ops, "_consumed_qty_by_batch", return_value={}),
            patch.object(mes_ops, "_apply_pre_consumed_cost_to_finished_item"),
            patch.object(mes_ops, "_metered_items", return_value=set(metered)),
            patch.object(mes_ops, "_wip_inflow_by_item", return_value=dict(inflow)),
            patch.object(mes_ops, "_wip_actual_qty",
                         side_effect=lambda item, _wh: float(on_hand.get(item, 0.0))),
            patch.object(mes_ops.frappe, "get_precision", return_value=3),
            patch.object(mes_ops.frappe, "log_error", side_effect=lambda **kw: logged.append(kw)),
            patch.object(mes_ops.frappe.utils, "now_datetime", return_value="2026-09-17 12:00:00"),
            patch.object(mes_ops.frappe.db, "get_value", side_effect=db_get_value),
            patch.object(mes_ops.frappe.db, "get_single_value", side_effect=single_value),
            patch.object(mes_ops.frappe.db, "set_value"),
            patch.object(mes_ops.frappe, "new_doc", return_value=se),
        ]

    def close(self, bom_items, consumed=None, metered=(WATER,), inflow=None,
              on_hand=None, sfg_codes=(), path="close"):
        """Run one of the two close paths and return (rows, logged)."""
        se, logged = FakeStockEntry(), []
        if inflow is None:
            inflow = {WATER: WATER_TRANSFERRED}
        if on_hand is None:
            # Enough of everything unless a test says otherwise, so the
            # warehouse balance is not silently the thing under test.
            on_hand = {row["item_code"]: 999.0 for row in bom_items}

        with ExitStack() as stack:
            for p in self._patches(bom_items, consumed or {}, metered, inflow,
                                   on_hand, sfg_codes, se, logged):
                stack.enter_context(p)
            if path == "close":
                mes_ops._close_single_wo(
                    {"name": "MFG-WO-2026-00063"},
                    {"good": WO_QTY, "reject": 0.0, "packaging": []},
                    None,
                )
            else:
                mes_ops.complete_work_order("MFG-WO-2026-00063", WO_QTY)

        rows = [r for r in se.items
                if not r.get("is_finished_item") and not r.get("is_scrap_item")]
        return rows, logged

    @staticmethod
    def _water(qty):
        return [{"item_code": WATER, "qty": qty, "uom": "Litre"}]

    def _qty(self, rows, item_code):
        """The single row for `item_code`, or None when it was not emitted."""
        matching = [r for r in rows if r["item_code"] == item_code]
        self.assertLessEqual(len(matching), 1, msg=f"duplicate rows: {matching}")
        return matching[0]["qty"] if matching else None

    def _source(self, rows, item_code):
        return next(r["s_warehouse"] for r in rows if r["item_code"] == item_code)


class TestMeteredCloseQty(unittest.TestCase):
    """The decision itself, isolated from either loop."""

    def setUp(self):
        self.precision = patch.object(frappe, "get_precision", return_value=3)
        self.precision.start()
        self.addCleanup(self.precision.stop)

    def test_the_covered_tick_is_taken(self):
        """The reported case: 0.000333 L left after a 0.333 load, with the
        0.001 this order transferred still sitting in WIP."""
        self.assertEqual(_metered_close_qty(0.000333333, 0.001), 0.001)

    def test_a_whole_sub_tick_requirement_is_rounded_up(self):
        """Nothing loaded at all — water is not scannable — so the remainder is
        the full requirement and Start's rounded-up transfer covers it."""
        self.assertEqual(_metered_close_qty(WATER_REQUIRED, WATER_TRANSFERRED), 0.334)

    def test_an_exact_requirement_is_untouched(self):
        self.assertEqual(_metered_close_qty(2.0, 999.0), 2.0)

    def test_headroom_short_by_anything_falls_back_to_truncation(self):
        self.assertEqual(_metered_close_qty(0.000333333, 0.0009), 0.0)
        self.assertEqual(_metered_close_qty(WATER_REQUIRED, 0.333), 0.333)

    def test_no_headroom_leaves_todays_behaviour_exactly(self):
        self.assertEqual(_metered_close_qty(0.000333333, 0.0), 0.0)
        self.assertEqual(_metered_close_qty(0.000333333, -5.0), 0.0)

    def test_an_over_consumed_remainder_is_never_raised_toward_zero(self):
        """A negative remainder is a variance to report, not a quantity to
        post — rounding it up would erase the report."""
        for remaining in (-0.000667, -0.0012, -5.0):
            self.assertEqual(
                _metered_close_qty(remaining, 999.0),
                mes_ops.truncate_qty(remaining),
                msg=f"remaining={remaining}",
            )

    def test_the_result_is_only_ever_truncation_or_one_tick_above(self):
        """The property, not the cases: this can raise by a single tick and can
        never lower, whatever it is handed."""
        cases = [0.0, 1e-9, 0.0004, 0.000333333, 0.0015, WATER_REQUIRED, 2.0,
                 3.555555, 106.6667, -0.0004, -0.000667, -2.0]
        for remaining in cases:
            for headroom in (-1.0, 0.0, 0.0005, 0.001, 0.334, 1e9):
                got = _metered_close_qty(remaining, headroom)
                floor_ = mes_ops.truncate_qty(remaining)
                msg = f"remaining={remaining} headroom={headroom} -> {got}"
                self.assertGreaterEqual(got, floor_, msg=msg)
                self.assertLessEqual(got, floor_ + mes_ops.qty_tick() * 1.000001, msg=msg)
                if got > floor_:
                    self.assertGreaterEqual(headroom, got, msg=msg)


class TestWipActualQty(unittest.TestCase):
    def test_a_missing_bin_reads_as_nothing_on_hand(self):
        with patch.object(mes_ops.frappe.db, "get_value", return_value=None):
            self.assertEqual(_wip_actual_qty(WATER, WIP), 0.0)

    def test_a_broken_lookup_reads_as_nothing_on_hand(self):
        with patch.object(mes_ops.frappe.db, "get_value", side_effect=Exception("boom")):
            self.assertEqual(_wip_actual_qty(WATER, WIP), 0.0)

    def test_missing_arguments_read_as_nothing_on_hand(self):
        self.assertEqual(_wip_actual_qty("", WIP), 0.0)
        self.assertEqual(_wip_actual_qty(WATER, ""), 0.0)

    def test_the_bin_balance_is_returned(self):
        with patch.object(mes_ops.frappe.db, "get_value", return_value="0.001000000"):
            self.assertEqual(_wip_actual_qty(WATER, WIP), 0.001)


class TestMeteredHeadroom(unittest.TestCase):
    """Neither ceiling is sufficient alone, so the lower one wins."""

    def _headroom(self, inflow, consumed, on_hand):
        with patch.object(mes_ops, "_wip_actual_qty", return_value=on_hand):
            return _metered_headroom(WATER, WIP, {WATER: inflow} if inflow else {}, consumed)

    def test_the_warehouse_balance_can_be_the_binding_one(self):
        """This order transferred its own tick in, but the pool no longer has
        it — another order on the line drank it."""
        self.assertEqual(self._headroom(0.334, 0.333, 0.0), 0.0)

    def test_this_orders_own_claim_can_be_the_binding_one(self):
        """The pool is full of somebody else's material; none of it is ours."""
        self.assertEqual(self._headroom(0.0, 0.0, 500.0), 0.0)
        self.assertEqual(self._headroom(0.334, 0.334, 500.0), 0.0)

    def test_what_is_already_consumed_no_longer_counts(self):
        self.assertAlmostEqual(self._headroom(0.334, 0.333, 500.0), 0.001, places=9)

    def test_a_legacy_over_consumption_reads_as_negative_not_zero(self):
        """An order that took more than it brought has no claim at all, and the
        raise must see that rather than a floor of zero."""
        self.assertLess(self._headroom(3.556, 3.557, 500.0), 0.0)


class TestCloseProduction(MeteredCloseHarness):
    """Close Production — ``_close_single_wo``."""

    PATH = "close"

    def test_the_stranded_tick_is_consumed(self):
        """MFG-WO-2026-00063: 0.334 transferred, 0.333 loaded, 0.001 left that
        only a hand-written Stock Entry could ever clear."""
        rows, _ = self.close(
            self._water(WATER_REQUIRED),
            consumed={WATER: 0.333},
            inflow={WATER: WATER_TRANSFERRED},
            on_hand={WATER: 0.001},
            path=self.PATH,
        )

        self.assertEqual(self._qty(rows, WATER), 0.001)
        self.assertEqual(self._source(rows, WATER), WIP)

    def test_an_unloaded_requirement_consumes_what_start_transferred(self):
        """The shape after metered items left the consume dialog: nothing is
        loaded, so the close posts the whole rounded-up requirement and WIP
        ends at zero instead of accruing a tick per order."""
        rows, _ = self.close(
            self._water(WATER_REQUIRED),
            inflow={WATER: WATER_TRANSFERRED},
            on_hand={WATER: WATER_TRANSFERRED},
            path=self.PATH,
        )

        self.assertEqual(self._qty(rows, WATER), WATER_TRANSFERRED)

    def test_a_tick_the_warehouse_does_not_hold_is_not_posted(self):
        """WIP is shared: another order may already have drunk this one's
        leftover. Posting it anyway would fail ERPNext's negative-stock check
        and block the close — the exact outage this whole area exists to
        prevent."""
        rows, _ = self.close(
            self._water(WATER_REQUIRED),
            consumed={WATER: 0.333},
            inflow={WATER: WATER_TRANSFERRED},
            on_hand={WATER: 0.0},
            path=self.PATH,
        )

        self.assertIsNone(self._qty(rows, WATER))

    def test_a_tick_this_order_never_brought_in_is_not_posted(self):
        """No transfer on record means no claim on the pool, however much of
        the item happens to be sitting in it."""
        rows, _ = self.close(
            self._water(WATER_REQUIRED),
            consumed={WATER: 0.333},
            inflow={},
            on_hand={WATER: 500.0},
            path=self.PATH,
        )

        self.assertIsNone(self._qty(rows, WATER))

    def test_an_item_that_is_not_metered_still_truncates(self):
        """Ample stock and ample inflow: only the metered list decides."""
        rows, _ = self.close(
            [{"item_code": CORN, "qty": 5.0004, "uom": "Kg"}],
            consumed={CORN: 5.0},
            metered=(WATER,),
            inflow={CORN: 6.0},
            on_hand={CORN: 6.0},
            path=self.PATH,
        )

        self.assertIsNone(self._qty(rows, CORN))

    def test_the_whole_metered_list_is_honoured_not_just_water(self):
        """Nothing here is special-cased to water: the setting drives it."""
        rows, _ = self.close(
            [{"item_code": CORN, "qty": 5.0004, "uom": "Kg"}],
            consumed={CORN: 5.0},
            metered=(CORN,),
            inflow={CORN: 6.0},
            on_hand={CORN: 6.0},
            path=self.PATH,
        )

        self.assertEqual(self._qty(rows, CORN), 0.001)

    def test_an_empty_metered_list_changes_nothing(self):
        rows, _ = self.close(
            self._water(WATER_REQUIRED),
            consumed={WATER: 0.333},
            metered=(),
            path=self.PATH,
        )

        self.assertIsNone(self._qty(rows, WATER))

    def test_over_consumption_is_still_reported_and_posts_nothing(self):
        """Rounding up must not turn a variance into a consumption row."""
        rows, logged = self.close(
            self._water(WATER_REQUIRED),
            consumed={WATER: WATER_TRANSFERRED},
            on_hand={WATER: 500.0},
            path=self.PATH,
        )

        self.assertIsNone(self._qty(rows, WATER))
        over = [m for m in logged if m.get("title") == "Material Over-Consumption"]
        self.assertEqual(len(over), 1)
        self.assertIn("0.0007", over[0]["message"])


class TestEndWorkOrder(TestCloseProduction):
    """End WO — ``complete_work_order``. The same loop, written twice in the
    codebase, so it is tested twice here: the two must never drift."""

    PATH = "complete"


class TestSemiFinishedComponentIsLeftAlone(MeteredCloseHarness):
    def test_a_metered_sfg_component_is_not_raised(self):
        """A semi-finished component is consumed out of the Semi-finished
        warehouse, so WIP headroom says nothing about it. Only Close Production
        sources rows that way; End WO has no such branch."""
        rows, _ = self.close(
            [{"item_code": "SFG10002", "qty": 5.0004, "uom": "Kg"}],
            consumed={"SFG10002": 5.0},
            metered=("SFG10002",),
            inflow={"SFG10002": 99.0},
            on_hand={"SFG10002": 99.0},
            sfg_codes=("SFG10002",),
        )

        self.assertIsNone(self._qty(rows, "SFG10002"))

    def test_the_same_component_would_be_raised_out_of_wip(self):
        """Control for the test above: the only difference is where the row is
        sourced from."""
        rows, _ = self.close(
            [{"item_code": "SFG10002", "qty": 5.0004, "uom": "Kg"}],
            consumed={"SFG10002": 5.0},
            metered=("SFG10002",),
            inflow={"SFG10002": 99.0},
            on_hand={"SFG10002": 99.0},
            sfg_codes=(),
        )

        self.assertEqual(self._qty(rows, "SFG10002"), 0.001)
        self.assertEqual(self._source(rows, "SFG10002"), WIP)


if __name__ == "__main__":
    unittest.main()
