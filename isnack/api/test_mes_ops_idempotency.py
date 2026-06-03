# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for Operator Hub stock-movement idempotency and concurrency safety.

These cover the duplicate / over-transfer corruption that motivated the
locking + submitted-Stock-Entry-as-source-of-truth rework in
``transfer_staged_to_wip`` / ``close_production`` / ``_close_single_wo``.

The functions under test call many module-level helpers; we patch those so the
tests assert behaviour (was a Material Transfer for Manufacture created? with
what fg_completed_qty? was surplus still swept?) without needing a live site.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

import isnack.api.mes_ops as mes_ops
from isnack.api.mes_ops import transfer_staged_to_wip, set_work_order_state, _close_single_wo


class FakeStockEntry:
    """Minimal stand-in for a Stock Entry doc that records appended rows and
    whether it was inserted/submitted, while accepting arbitrary attributes."""

    def __init__(self):
        self.items = []
        self.flags = MagicMock()
        self.name = "MAT-STE-NEW"
        self.inserted = False
        self.submitted = False

    def append(self, table, row):
        self.items.append(row)

    def insert(self):
        self.inserted = True

    def submit(self):
        self.submitted = True


def _wo(qty=332.0, company="Test Co", bom_no="BOM-001"):
    wo = MagicMock()
    wo.qty = qty
    wo.company = company
    wo.bom_no = bom_no
    wo.use_multi_level_bom = 0
    wo.actual_end_date = None
    wo.wip_warehouse = "WIP-A"
    wo.fg_warehouse = "FG-A"
    wo.production_item = "FG-ITEM"
    return wo


class TestTransferStagedToWipIdempotency(unittest.TestCase):
    """Scenarios 1, 2, 3, 7."""

    def _run(self, *, submitted_mtfm, staged_rows, already_moved, surplus=None):
        """Invoke transfer_staged_to_wip with all collaborators patched.

        Returns (result, new_doc_mock) so tests can assert whether an MTFM Stock
        Entry was created and how it was configured.
        """
        surplus = surplus or []
        new_doc = MagicMock(side_effect=lambda dt: FakeStockEntry())
        with patch.object(mes_ops, "_require_roles"), \
             patch.object(mes_ops, "_lock_work_order_for_update") as lock, \
             patch.object(mes_ops, "_default_line_staging", return_value="Stage-A"), \
             patch.object(mes_ops, "_default_line_wip", return_value="WIP-A"), \
             patch.object(mes_ops, "_submitted_mtfm_qty", return_value=submitted_mtfm), \
             patch.object(mes_ops, "_submitted_mtfm_item_qty_by_key", return_value=dict(already_moved)), \
             patch.object(mes_ops, "_sweep_surplus_to_wip", return_value=surplus) as sweep, \
             patch.object(mes_ops.frappe, "get_doc", return_value=_wo()), \
             patch.object(mes_ops.frappe.db, "sql", return_value=staged_rows), \
             patch.object(mes_ops.frappe, "new_doc", new_doc):
            result = transfer_staged_to_wip("MFG-WO-0001")
        return result, new_doc, lock, sweep

    def test_first_start_creates_one_mtfm(self):
        """Scenario 1a: fresh WO -> exactly one MTFM, WO locked first."""
        staged = [frappe._dict(item_code="RM1", batch_no="B1", uom="Kg", qty=100.0)]
        result, new_doc, lock, sweep = self._run(
            submitted_mtfm=0.0, staged_rows=staged, already_moved={},
        )
        # WO row was locked before anything else.
        lock.assert_called_once_with("MFG-WO-0001")
        # Exactly one MTFM Stock Entry created.
        new_doc.assert_called_once_with("Stock Entry")
        self.assertEqual(result["stock_entry"], "MAT-STE-NEW")

    def test_first_start_fg_completed_qty_and_rows(self):
        """Scenario 1a detail: fg_completed_qty == full qty, all rows moved."""
        staged = [
            frappe._dict(item_code="RM1", batch_no="B1", uom="Kg", qty=100.0),
            frappe._dict(item_code="RM2", batch_no="", uom="Nos", qty=5.0),
        ]
        created = {}
        def make(dt):
            se = FakeStockEntry()
            created["se"] = se
            return se
        with patch.object(mes_ops, "_require_roles"), \
             patch.object(mes_ops, "_lock_work_order_for_update"), \
             patch.object(mes_ops, "_default_line_staging", return_value="Stage-A"), \
             patch.object(mes_ops, "_default_line_wip", return_value="WIP-A"), \
             patch.object(mes_ops, "_submitted_mtfm_qty", return_value=0.0), \
             patch.object(mes_ops, "_submitted_mtfm_item_qty_by_key", return_value={}), \
             patch.object(mes_ops, "_sweep_surplus_to_wip", return_value=[]), \
             patch.object(mes_ops.frappe, "get_doc", return_value=_wo(qty=332.0)), \
             patch.object(mes_ops.frappe.db, "sql", return_value=staged), \
             patch.object(mes_ops.frappe, "new_doc", side_effect=make):
            transfer_staged_to_wip("MFG-WO-0001")

        se = created["se"]
        self.assertEqual(se.purpose, "Material Transfer for Manufacture")
        self.assertEqual(se.stock_entry_type, "Material Transfer for Manufacture")
        self.assertEqual(se.fg_completed_qty, 332.0)
        self.assertEqual(len(se.items), 2)
        # Batch row carries batch_no + use_serial_batch_fields; non-batch row does not.
        self.assertEqual(se.items[0]["batch_no"], "B1")
        self.assertEqual(se.items[0]["use_serial_batch_fields"], 1)
        self.assertNotIn("batch_no", se.items[1])
        self.assertTrue(se.submitted)

    def test_second_start_creates_no_mtfm(self):
        """Scenario 1b & 7: WO already fully transferred -> no MTFM at all,
        not even a zero-qty one. Surplus sweep still runs."""
        staged = [frappe._dict(item_code="RM1", batch_no="B1", uom="Kg", qty=100.0)]
        result, new_doc, lock, sweep = self._run(
            submitted_mtfm=332.0, staged_rows=staged,
            already_moved={("RM1", "B1", "Kg"): 100.0},
        )
        new_doc.assert_not_called()           # no Stock Entry built
        self.assertIsNone(result["stock_entry"])
        sweep.assert_called_once()            # surplus still swept

    def test_already_transferred_still_sweeps_surplus(self):
        """Scenario 2: normal MTFM skipped, surplus moved via the sweep."""
        result, new_doc, lock, sweep = self._run(
            submitted_mtfm=332.0, staged_rows=[], already_moved={},
            surplus=["MAT-STE-SURPLUS"],
        )
        new_doc.assert_not_called()
        sweep.assert_called_once()
        self.assertEqual(result["surplus_transfers"], ["MAT-STE-SURPLUS"])

    def test_partial_transfer_moves_only_remainder(self):
        """Scenario 3: prior MTFM covered part of qty and part of a staged row;
        new MTFM is for the remaining FG qty and the net-remaining row qty."""
        staged = [frappe._dict(item_code="RM1", batch_no="B1", uom="Kg", qty=100.0)]
        created = {}
        def make(dt):
            se = FakeStockEntry()
            created["se"] = se
            return se
        with patch.object(mes_ops, "_require_roles"), \
             patch.object(mes_ops, "_lock_work_order_for_update"), \
             patch.object(mes_ops, "_default_line_staging", return_value="Stage-A"), \
             patch.object(mes_ops, "_default_line_wip", return_value="WIP-A"), \
             patch.object(mes_ops, "_submitted_mtfm_qty", return_value=200.0), \
             patch.object(mes_ops, "_submitted_mtfm_item_qty_by_key",
                          return_value={("RM1", "B1", "Kg"): 60.0}), \
             patch.object(mes_ops, "_sweep_surplus_to_wip", return_value=[]), \
             patch.object(mes_ops.frappe, "get_doc", return_value=_wo(qty=332.0)), \
             patch.object(mes_ops.frappe.db, "sql", return_value=staged), \
             patch.object(mes_ops.frappe, "new_doc", side_effect=make):
            transfer_staged_to_wip("MFG-WO-0001")

        se = created["se"]
        # Remaining FG qty = 332 - 200.
        self.assertAlmostEqual(se.fg_completed_qty, 132.0)
        # Net row qty = 100 - 60 already moved.
        self.assertEqual(len(se.items), 1)
        self.assertAlmostEqual(se.items[0]["qty"], 40.0)

    def test_no_zero_qty_mtfm_when_rows_already_moved(self):
        """Scenario 7 variant: remaining FG qty > 0 but every staged row was
        already physically moved -> no MTFM created."""
        staged = [frappe._dict(item_code="RM1", batch_no="B1", uom="Kg", qty=100.0)]
        result, new_doc, lock, sweep = self._run(
            submitted_mtfm=0.0, staged_rows=staged,
            already_moved={("RM1", "B1", "Kg"): 100.0},
        )
        new_doc.assert_not_called()
        self.assertIsNone(result["stock_entry"])


class TestStartFailsHardOnTransferError(unittest.TestCase):
    """Scenario 6."""

    def test_start_does_not_advance_when_transfer_fails(self):
        thrown = RuntimeError("transfer blew up")

        def fake_throw(*args, **kwargs):
            raise RuntimeError("frappe.throw")

        with patch.object(mes_ops, "_require_roles"), \
             patch.object(mes_ops, "_assert_not_ended"), \
             patch.object(mes_ops, "_storekeeper_stage_status", return_value="Staged"), \
             patch.object(mes_ops, "transfer_staged_to_wip", side_effect=thrown), \
             patch.object(mes_ops.frappe, "get_doc", return_value=_wo()), \
             patch.object(mes_ops.frappe, "log_error") as log_error, \
             patch.object(mes_ops.frappe.utils, "now_datetime", return_value="2026-06-03 10:00:00"), \
             patch.object(mes_ops.frappe.db, "set_value") as set_value, \
             patch.object(mes_ops.frappe, "throw", side_effect=fake_throw):
            with self.assertRaises(RuntimeError):
                set_work_order_state("MFG-WO-0001", "Start")

        # The failure was logged and the WO status was never written.
        log_error.assert_called_once()
        set_value.assert_not_called()


class TestCloseSingleWoIdempotency(unittest.TestCase):
    """Scenarios 4 and 5."""

    def test_skips_manufacture_when_already_produced(self):
        """Scenario 5: a submitted Manufacture entry already covers the WO ->
        no second Manufacture is booked; WO is marked Completed."""
        with patch.object(mes_ops.frappe, "get_doc", return_value=_wo(qty=332.0)), \
             patch.object(mes_ops, "_submitted_mtfm_qty", return_value=332.0), \
             patch.object(mes_ops, "_submitted_manufacture_qty", return_value=332.0), \
             patch.object(mes_ops.frappe.utils, "now_datetime", return_value="2026-06-03 10:00:00"), \
             patch.object(mes_ops.frappe, "new_doc") as new_doc, \
             patch.object(mes_ops.frappe.db, "set_value") as set_value:
            _close_single_wo({"name": "MFG-WO-0001"},
                             {"good": 332.0, "reject": 0, "packaging": []}, "ABC-001")

        new_doc.assert_not_called()  # no Manufacture Stock Entry created
        # WO marked Completed.
        status_calls = [c for c in set_value.call_args_list
                        if c[0][0] == "Work Order" and isinstance(c[0][2], dict)
                        and c[0][2].get("status") == "Completed"]
        self.assertTrue(status_calls)

    def test_excess_mtfm_blocks_close(self):
        """Pre-check: submitted MTFM exceeding planned qty stops the close."""
        def fake_throw(*args, **kwargs):
            raise RuntimeError("excess")

        with patch.object(mes_ops.frappe, "get_doc", return_value=_wo(qty=332.0)), \
             patch.object(mes_ops, "_submitted_mtfm_qty", return_value=664.0), \
             patch.object(mes_ops.frappe, "log_error"), \
             patch.object(mes_ops.frappe, "new_doc") as new_doc, \
             patch.object(mes_ops.frappe, "throw", side_effect=fake_throw):
            with self.assertRaises(RuntimeError):
                _close_single_wo({"name": "MFG-WO-0001"},
                                 {"good": 332.0, "reject": 0, "packaging": []}, "ABC-001")
        new_doc.assert_not_called()

    def test_late_surplus_swept_before_manufacture(self):
        """Scenario 4: surplus added after Start is swept (plain Material
        Transfer) before the Manufacture entry is built."""
        order = []

        def fake_sweep(wo_name, staging, wip, wo, *a, **k):
            order.append("sweep")
            return ["MAT-STE-SURPLUS"]

        def make(dt):
            order.append("manufacture_se")
            return FakeStockEntry()

        def db_get_value(doctype, name, field, *a, **k):
            if field == "stock_uom":
                return "Nos"
            if field == "has_batch_no":
                return 0
            return None

        with patch.object(mes_ops.frappe, "get_doc", return_value=_wo(qty=10.0)), \
             patch.object(mes_ops, "_submitted_mtfm_qty", return_value=10.0), \
             patch.object(mes_ops, "_submitted_manufacture_qty", return_value=0.0), \
             patch.object(mes_ops, "_default_line_target", return_value="FG-A"), \
             patch.object(mes_ops, "_default_line_wip", return_value="WIP-A"), \
             patch.object(mes_ops, "_default_line_staging", return_value="Stage-A"), \
             patch.object(mes_ops, "_sweep_surplus_to_wip", side_effect=fake_sweep) as sweep, \
             patch.object(mes_ops, "_get_consumed_materials_from_load", return_value={}), \
             patch.object(mes_ops, "_get_bom_items_for_quantity", return_value=[]), \
             patch.object(mes_ops, "_apply_pre_consumed_cost_to_finished_item"), \
             patch.object(mes_ops.frappe.utils, "now_datetime", return_value="2026-06-03 10:00:00"), \
             patch.object(mes_ops.frappe.db, "get_value", side_effect=db_get_value), \
             patch.object(mes_ops.frappe.db, "get_single_value", return_value="FG-A"), \
             patch.object(mes_ops.frappe.db, "set_value"), \
             patch.object(mes_ops.frappe, "new_doc", side_effect=make):
            _close_single_wo({"name": "MFG-WO-0001"},
                             {"good": 10.0, "reject": 0, "packaging": []}, "ABC-001")

        sweep.assert_called_once()
        # Surplus sweep happens before the Manufacture Stock Entry is built.
        self.assertEqual(order[0], "sweep")
        self.assertIn("manufacture_se", order)
        self.assertLess(order.index("sweep"), order.index("manufacture_se"))


if __name__ == "__main__":
    unittest.main()
