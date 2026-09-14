# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Material may only be loaded once a Work Order has been Started.

Start is what moves a Work Order's staged material from the line's staging
warehouse into its WIP warehouse. Loading before that does not fail on its
own — WIP is shared across the Work Orders on a line, so the scan quietly
consumes whatever stock of the item happens to be there. On 2026-09-11 that
booked 43.2 kg of seasoning from batch AV-426, swept into WIP five weeks
earlier, against MFG-WO-2026-00064, while DateProd26022026 — the batch the
storekeeper had staged for it — stayed in EXT1-STAGING.
"""

import unittest
from unittest.mock import patch

import frappe

import isnack.api.mes_ops as mes_ops
from isnack.api.mes_ops import _assert_started

WO_NAME = "MFG-WO-2026-00064"


class TestAssertStarted(unittest.TestCase):
    def test_a_started_work_order_passes(self):
        with patch("frappe.db.get_value", return_value="2026-09-11 13:13:56"):
            _assert_started(WO_NAME)          # no throw

    def test_an_unstarted_work_order_is_refused(self):
        with patch("frappe.db.get_value", return_value=None):
            with self.assertRaises(frappe.ValidationError):
                _assert_started(WO_NAME)

    def test_the_message_names_the_order_and_the_remedy(self):
        with patch("frappe.db.get_value", return_value=None):
            try:
                _assert_started(WO_NAME)
            except frappe.ValidationError as e:
                msg = str(e)
            else:
                self.fail("expected a ValidationError")
        self.assertIn(WO_NAME, msg)
        self.assertIn("Press Start", msg)

    def test_it_reads_actual_start_date_not_status(self):
        """Pause sets status back to Stopped; actual_start_date is never cleared,
        so a paused Work Order must still accept material."""
        with patch("frappe.db.get_value") as gv:
            gv.return_value = "2026-09-11 13:13:56"
            _assert_started(WO_NAME)
            self.assertEqual(gv.call_args[0][2], "actual_start_date")

    def test_no_work_order_is_not_this_guard_s_business(self):
        with patch("frappe.db.get_value", side_effect=AssertionError("must not query")):
            _assert_started("")
            _assert_started(None)


class TestConsumptionIsGuarded(unittest.TestCase):
    """Both operator entry points post through _post_material_consumption_for_wo,
    so the guard belongs there rather than on each of them."""

    def test_the_poster_asserts_started_before_touching_stock(self):
        with patch.object(mes_ops, "_assert_not_ended"), \
             patch.object(mes_ops, "_assert_started",
                          side_effect=frappe.ValidationError("not started")) as guard, \
             patch("frappe.get_doc", side_effect=AssertionError("must not reach the Work Order")):
            with self.assertRaises(frappe.ValidationError):
                mes_ops._post_material_consumption_for_wo(
                    WO_NAME, [{"item_code": "RM20011", "qty": 43.2}]
                )
        guard.assert_called_once_with(WO_NAME)


class TestQueueExposesStarted(unittest.TestCase):
    """The hub greys the Load buttons out from this flag, so the queue has to
    carry it."""

    def rows(self, actual_start_date):
        wo = frappe._dict(
            name=WO_NAME, production_item="SFG10001", item_name="Corn Mix", qty=150.0,
            status="Not Started", custom_factory_line="CORN MIX", custom_production_ended=0,
            planned_start_date=None, actual_start_date=actual_start_date, creation=None,
        )
        with patch.object(mes_ops, "_get_user_line", return_value=None), \
             patch.object(mes_ops, "_storekeeper_stage_status", return_value="Staged"), \
             patch.object(mes_ops, "_is_fg", return_value=False), \
             patch.object(mes_ops, "_line_for_work_order", return_value="CORN MIX"), \
             patch("frappe.get_meta") as meta, \
             patch("frappe.get_all", return_value=[wo]):
            meta.return_value.has_field.return_value = True
            return mes_ops.get_line_queue(line="CORN MIX")

    def test_unstarted(self):
        self.assertIs(self.rows(None)[0]["started"], False)

    def test_started(self):
        self.assertIs(self.rows("2026-09-11 13:13:56")[0]["started"], True)


if __name__ == "__main__":
    unittest.main()
