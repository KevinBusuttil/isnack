# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""An order ended before it was started must not get stuck.

On 2026-10-21 MFG-WO-2026-00086 (300 cartons of FG10020) was ended without
Start being pressed. Start is what moves the staged packaging from the line's
staging warehouse into WIP, and an ended order cannot be started, so its 300
cartons and 20 kg of film stayed in Semi-finished. Close Production then swept
in the 10 surplus cartons and stopped on ERPNext's "the Available qty 10.0 is
less than the Required Qty 305.0 in the warehouse EXT1-WIP - ISN" — at 300 as
much as at 305. Nothing about the new item had anything to do with it.

These tests cover the fixes: End WO requires Start, Close Production refuses a
never-started order in its own words, a Production Manager can undo End WO,
ending again cannot consume the semi-finished material twice, and the dialog's
packaging check counts the surplus the close sweeps in for a row with no batch.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import frappe

import isnack.api.mes_ops as mes_ops

WO = "MFG-WO-2026-00086"
WIP = "EXT1-WIP - ISN"


class WorkOrderStub:
    def __init__(self, status="Not Started", ended=0, docstatus=1):
        self.name = WO
        self.status = status
        self.custom_production_ended = ended
        self.docstatus = docstatus
        self.qty = 300.0
        self.production_item = "FG10020"
        self.company = "Isnack"
        self.bom_no = "BOM-FG10020-002"
        self.comments = []
        self.db_set = MagicMock()

    def get(self, field, default=None):
        return getattr(self, field, default)

    def add_comment(self, _kind, text):
        self.comments.append(text)


def end(wo, started, sfg_usage=None, consumed=None):
    """Run end_work_order on a legacy-mode finished-good order."""
    with patch.object(mes_ops, "_require_roles"), \
            patch.object(mes_ops.frappe, "get_doc", return_value=wo), \
            patch.object(mes_ops.frappe.db, "get_value",
                         return_value="2026-10-21 10:40:00" if started else None), \
            patch.object(mes_ops, "_get_consumed_materials_from_load", return_value=consumed or {}), \
            patch.object(mes_ops, "_end_wo_consumption_summary",
                         return_value={"can_end": True, "items": [], "shortfalls": 0, "tolerance_pct": 5}), \
            patch.object(mes_ops, "_wo_closes_at_end", return_value=False), \
            patch.object(mes_ops.frappe, "get_precision", return_value=3), \
            patch.object(mes_ops, "_post_sfg_consumption") as post:
        result = mes_ops.end_work_order(WO, sfg_usage=json.dumps(sfg_usage) if sfg_usage else None)
    return result, post


class TestEndWoRequiresStart(unittest.TestCase):
    def test_a_never_started_order_is_refused(self):
        wo = WorkOrderStub()
        with self.assertRaises(frappe.ValidationError) as caught:
            end(wo, started=False)

        self.assertIn("has not been started", str(caught.exception))
        self.assertIn("Press Start", str(caught.exception))
        wo.db_set.assert_not_called()

    def test_it_is_refused_before_any_semi_finished_is_consumed(self):
        """WO-00086's End WO consumed 160 kg of corn mix and 120 kg of slurry
        before anything checked the order had been started."""
        wo = WorkOrderStub()
        with patch.object(mes_ops, "_post_sfg_consumption") as post:
            with self.assertRaises(frappe.ValidationError):
                end(wo, started=False,
                    sfg_usage=[{"item_code": "SFG10001", "qty": 160}])
        post.assert_not_called()

    def test_a_started_order_ends(self):
        wo = WorkOrderStub(status="In Process")
        result, _post = end(wo, started=True)

        self.assertTrue(result["success"])
        wo.db_set.assert_called_once_with("custom_production_ended", 1, commit=True)


class TestEndingAgainDoesNotConsumeTwice(unittest.TestCase):
    def test_the_whole_figure_is_consumed_the_first_time(self):
        wo = WorkOrderStub(status="In Process")
        _result, post = end(wo, started=True,
                            sfg_usage=[{"item_code": "SFG10001", "qty": 160},
                                       {"item_code": "SFG10005", "qty": 120}])

        self.assertEqual(post.call_args[0][1], [{"item_code": "SFG10001", "qty": 160.0},
                                                {"item_code": "SFG10005", "qty": 120.0}])
        self.assertEqual(wo.comments, ["Work Order ended - awaiting production closure"])

    def test_re_entering_what_is_already_recorded_consumes_nothing(self):
        """Undo End WO, Start, End WO again with the same figures: the 160 kg
        and 120 kg were consumed on the 21st and stay consumed once."""
        wo = WorkOrderStub(status="In Process")
        _result, post = end(wo, started=True,
                            sfg_usage=[{"item_code": "SFG10001", "qty": 160},
                                       {"item_code": "SFG10005", "qty": 120}],
                            consumed={"SFG10001": 160.0, "SFG10005": 120.0})

        post.assert_not_called()
        note = next(c for c in wo.comments if c.startswith("End WO semi-finished usage"))
        self.assertIn("SFG10001: 160 entered, 160 already recorded, 0 consumed now", note)

    def test_only_the_part_not_yet_recorded_is_consumed(self):
        wo = WorkOrderStub(status="In Process")
        _result, post = end(wo, started=True,
                            sfg_usage=[{"item_code": "SFG10001", "qty": 165}],
                            consumed={"SFG10001": 160.0})

        self.assertEqual(post.call_args[0][1], [{"item_code": "SFG10001", "qty": 5.0}])


class TestSfgUsageNotYetRecorded(unittest.TestCase):
    def net(self, rows, consumed):
        wo = WorkOrderStub()
        with patch.object(mes_ops, "_get_consumed_materials_from_load", return_value=consumed), \
                patch.object(mes_ops.frappe, "get_precision", return_value=3):
            return mes_ops._sfg_usage_not_yet_recorded(wo, rows), wo.comments

    def test_float_noise_does_not_cost_a_tick(self):
        rows, _notes = self.net([{"item_code": "SFG10001", "qty": 0.3}], {"SFG10001": 0.1})
        self.assertEqual(rows, [{"item_code": "SFG10001", "qty": 0.2}])

    def test_blank_and_zero_rows_are_ignored(self):
        rows, notes = self.net([{"item_code": "", "qty": 5}, {"item_code": "SFG10001", "qty": 0},
                                {"item_code": "SFG10005", "qty": "x"}], {})
        self.assertEqual((rows, notes), ([], []))

    def test_repeated_rows_for_one_item_add_up(self):
        rows, _notes = self.net([{"item_code": "SFG10001", "qty": 100},
                                 {"item_code": "SFG10001", "qty": 60}], {})
        self.assertEqual(rows, [{"item_code": "SFG10001", "qty": 160.0}])


def undo(wo, manufactured=0.0, reason="Ended before Start by mistake", roles_ok=True):
    def require(roles):
        if roles != ["Production Manager"]:
            raise AssertionError(f"unexpected roles {roles}")
        if not roles_ok:
            raise frappe.PermissionError("Not permitted")

    with patch.object(mes_ops, "_require_roles", side_effect=require), \
            patch.object(mes_ops, "_lock_work_order_for_update") as lock, \
            patch.object(mes_ops.frappe, "get_doc", return_value=wo), \
            patch.object(mes_ops, "_submitted_manufacture_qty", return_value=manufactured):
        result = mes_ops.undo_end_work_order(WO, reason=reason)
    lock.assert_called_once_with(WO)
    return result


class TestUndoEndWo(unittest.TestCase):
    def test_a_manager_reopens_an_ended_order_with_a_reason(self):
        wo = WorkOrderStub(ended=1)
        result = undo(wo)

        self.assertTrue(result["success"])
        wo.db_set.assert_called_once_with("custom_production_ended", 0)
        self.assertEqual(len(wo.comments), 1)
        self.assertIn("End WO undone by", wo.comments[0])
        self.assertIn("Ended before Start by mistake", wo.comments[0])

    def test_only_a_production_manager_may(self):
        with self.assertRaises(frappe.PermissionError):
            undo(WorkOrderStub(ended=1), roles_ok=False)

    def test_a_reason_is_required(self):
        with patch.object(mes_ops, "_require_roles"):
            with self.assertRaises(frappe.ValidationError):
                mes_ops.undo_end_work_order(WO, reason="  ")

    def test_an_order_that_is_not_ended_is_refused(self):
        wo = WorkOrderStub(ended=0)
        with self.assertRaises(frappe.ValidationError):
            undo(wo)
        wo.db_set.assert_not_called()

    def test_a_closed_order_is_refused(self):
        """Close Production clears the ended flag, so a closed order arrives
        with ended=0 and must still be told it is closed."""
        for wo, manufactured in ((WorkOrderStub(status="Completed", ended=0), 0.0),
                                 (WorkOrderStub(status="In Process", ended=1), 305.0)):
            with self.assertRaises(frappe.ValidationError) as caught:
                undo(wo, manufactured=manufactured)
            self.assertIn("already been closed", str(caught.exception))
            wo.db_set.assert_not_called()


ENDED_WO_ROW = {
    "name": WO, "qty": 300.0, "production_item": "FG10020", "company": "Isnack",
    "bom_no": "BOM-FG10020-002", "fg_warehouse": "Finished Goods - ISN",
    "wip_warehouse": WIP, "custom_factory_line": "CORN EXTRUSION",
    "actual_start_date": None,
}


class TestCloseProductionRefusesANeverStartedOrder(unittest.TestCase):
    def close(self, row):
        groups = [{"production_item": "FG10020", "good_qty": 305, "reject_qty": 0,
                   "batch_no": "DDD-444", "work_orders": [WO],
                   "packaging_usage": [{"item_code": "CR30002", "qty": 305, "batch_no": None}]}]
        with patch.object(mes_ops, "_require_roles"), \
                patch.object(mes_ops.frappe, "get_all", return_value=[dict(row)]), \
                patch.object(mes_ops, "_line_for_work_order", return_value="CORN EXTRUSION"), \
                patch.object(mes_ops.frappe.db, "get_value", return_value=1), \
                patch.object(mes_ops, "_validate_close_production"), \
                patch.object(mes_ops, "_lock_work_orders_for_update"), \
                patch.object(mes_ops, "_close_single_wo") as close_one:
            try:
                return mes_ops.close_production(groups=json.dumps(groups),
                                                lines=json.dumps(["CORN EXTRUSION"])), close_one
            except frappe.ValidationError as e:
                return e, close_one

    def test_it_is_refused_in_its_own_words_before_anything_is_booked(self):
        outcome, close_one = self.close(ENDED_WO_ROW)

        self.assertIsInstance(outcome, frappe.ValidationError)
        self.assertIn(f"{WO} were ended without being started", str(outcome))
        self.assertIn("Undo End WO", str(outcome))
        close_one.assert_not_called()

    def test_a_started_order_still_closes(self):
        outcome, close_one = self.close(dict(ENDED_WO_ROW, actual_start_date="2026-10-21 10:40:00"))

        self.assertTrue(outcome["success"])
        close_one.assert_called_once()

    def test_the_dialog_says_the_same_before_the_button_is_pressed(self):
        with patch.object(mes_ops, "_require_roles"), \
                patch.object(mes_ops.frappe, "get_all",
                             return_value=[{"name": WO, "qty": 300.0, "actual_start_date": None}]), \
                patch.object(mes_ops.frappe.db, "get_single_value", return_value=10), \
                patch.object(mes_ops, "_bom_consumption_plan") as plan:
            data = mes_ops.get_close_production_coverage(json.dumps([WO]), 305, 0)

        self.assertEqual(data["not_started"], [WO])
        self.assertEqual(data["not_started_message"], mes_ops._never_started_message([WO]))
        self.assertEqual((data["short"], data["packaging_short"]), ([], []))
        plan.assert_not_called()


class TestPackagingCheckForARowWithNoBatch(unittest.TestCase):
    """WO-00086's dialog said "0 in EXT1-WIP - ISN, 305 short" while the close
    itself swept in 10 cartons first and reported Available 10."""

    SURPLUS = {("CR30002", "jimm0709", WIP): 10.0, ("CR30002", "other", WIP): 2.0,
               ("PM40009", "298/26", WIP): 5.0}

    def shortfalls(self, wanted):
        with patch.object(mes_ops, "_surplus_due_into_wip", return_value=dict(self.SURPLUS)), \
                patch.object(mes_ops, "_packaging_on_hand", return_value=0.0), \
                patch.object(mes_ops.frappe.db, "get_value", return_value="x"), \
                patch.object(mes_ops.frappe, "get_precision", return_value=3):
            return {r["item_code"]: (r["available_qty"], r["short_qty"])
                    for r in mes_ops._packaging_shortfalls(wanted, [WO])}

    def test_a_row_with_no_batch_counts_surplus_of_every_batch(self):
        got = self.shortfalls({("CR30002", "", WIP): 305.0})
        self.assertEqual(got, {"CR30002": (12.0, 293.0)})

    def test_a_row_with_a_batch_counts_only_that_batch(self):
        got = self.shortfalls({("CR30002", "jimm0709", WIP): 305.0})
        self.assertEqual(got, {"CR30002": (10.0, 295.0)})


if __name__ == "__main__":
    unittest.main()
