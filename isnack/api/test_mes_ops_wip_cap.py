# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""A Work Order may only consume what it itself brought into the shared WIP.

CORN MIX, SLURRY 1 and CORN EXTRUSION all draw on EXT1-WIP, and nothing in
ERPNext reserves a Work Order's material inside it. The only ceiling used to be
the over-consumption threshold, which is measured against the recipe rather
than against the stock the order actually has: an order consumed its own 150 kg
and then, fifteen seconds later, the 10 kg staged for the next one, which could
then not consume its own material.

The ceiling counts every route into this order's WIP warehouse, not just the
transfer at Start — a Material Request fulfilled mid-run and surplus swept in
at close arrive as plain Material Transfers, and refusing those would take back
what the storekeeper deliberately handed over.
"""

import unittest
from unittest.mock import patch

import frappe

import isnack.api.mes_ops as mes_ops

WO_NAME = "MFG-WO-2026-00062"
WIP = "EXT1-WIP - ISN"
ITEM = "CR30003"          # packaging: skips the BOM and threshold branches, so
PACKAGING_GROUP = "packaging materials"   # only the cap under test can fire


def _db_get_value(doctype, _name, field, *args, **kwargs):
    """The single-field lookups the poster makes. Nothing here is batch-tracked,
    so the batch requirement stays out of the way of the cap under test."""
    if doctype == "Work Order":
        return {"bom_no": "BOM-X", "qty": 300.0}.get(field)
    return 0 if field == "has_batch_no" else "Nos"


class FakeStockEntry:
    def __init__(self):
        self.items = []
        self.flags = frappe._dict()

    def append(self, _field, row):
        self.items.append(frappe._dict(row))
        return self.items[-1]

    def insert(self):
        pass

    def submit(self):
        self.name = "MAT-STE-TEST-0001"


class WipCapHarness(unittest.TestCase):
    def consume(self, rows, moved_in=0.0, already=0.0, item=ITEM, packaging=True):
        """Post a consumption of `rows` for a Work Order that brought `moved_in`
        into WIP and has already consumed `already`."""
        wo = frappe._dict(name=WO_NAME, company="Isnack", bom_no="BOM-X", qty=300.0,
                          produced_qty=0.0)
        se = FakeStockEntry()

        patches = [
            patch.object(mes_ops, "_assert_not_ended"),
            patch.object(mes_ops, "_assert_started"),
            patch.object(mes_ops, "_default_line_wip", return_value=WIP),
            patch.object(mes_ops, "_packaging_groups_global",
                         return_value={PACKAGING_GROUP} if packaging else set()),
            patch.object(mes_ops, "_get_item_group",
                         return_value=PACKAGING_GROUP if packaging else "raw material"),
            patch.object(mes_ops, "_validate_item_in_bom", return_value=(True, "")),
            patch.object(mes_ops, "_planned_required_qty", return_value=None),
            patch.object(mes_ops, "_wip_inflow_by_item", return_value={item: moved_in} if moved_in else {}),
            patch.object(mes_ops, "_consumed_by_item", return_value={item: already} if already else {}),
            patch("frappe.get_doc", return_value=wo),
            patch("frappe.new_doc", return_value=se),
            patch("frappe.db.exists", return_value=True),
            patch("frappe.db.get_value", side_effect=_db_get_value),
            patch("frappe.db.sql", return_value=[]),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        mes_ops._post_material_consumption_for_wo(WO_NAME, rows, allow_packaging=True)
        return se


class TestTheCap(WipCapHarness):
    def test_consuming_what_the_order_brought_in_is_allowed(self):
        se = self.consume([{"item_code": ITEM, "qty": 150.0}], moved_in=150.0)
        self.assertEqual(len(se.items), 1)
        self.assertEqual(se.items[0].qty, 150.0)

    def test_the_exact_remaining_balance_is_allowed(self):
        se = self.consume([{"item_code": ITEM, "qty": 50.0}], moved_in=150.0, already=100.0)
        self.assertEqual(se.items[0].qty, 50.0)

    def test_reaching_past_it_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self.consume([{"item_code": ITEM, "qty": 10.0}], moved_in=150.0, already=150.0)

    def test_the_message_says_what_the_order_has(self):
        try:
            self.consume([{"item_code": ITEM, "qty": 10.0}], moved_in=150.0, already=150.0)
        except frappe.ValidationError as e:
            msg = str(e)
        else:
            self.fail("expected a ValidationError")
        self.assertIn("brought 150", msg)
        self.assertIn("already consumed 150", msg)
        self.assertIn("another Work Order", msg)

    def test_rows_of_one_entry_accumulate(self):
        """A manual load posts several rows at once; together they must not
        exceed the balance either."""
        with self.assertRaises(frappe.ValidationError):
            self.consume(
                [{"item_code": ITEM, "qty": 100.0}, {"item_code": ITEM, "qty": 60.0}],
                moved_in=150.0,
            )

    def test_rows_that_fit_together_are_allowed(self):
        se = self.consume(
            [{"item_code": ITEM, "qty": 100.0}, {"item_code": ITEM, "qty": 50.0}],
            moved_in=150.0,
        )
        self.assertEqual([r.qty for r in se.items], [100.0, 50.0])

    def test_an_item_with_no_recorded_inflow_is_not_capped(self):
        """Guarded on moved_in, so anything reaching WIP by a route that does
        not name the Work Order behaves as it did before."""
        se = self.consume([{"item_code": ITEM, "qty": 999.0}], moved_in=0.0)
        self.assertEqual(se.items[0].qty, 999.0)

    def test_a_request_fulfilled_mid_run_raises_the_ceiling(self):
        """The 5 kg of a post-Start Material Request arrives as a plain Material
        Transfer. It counts, or release two's change 3 would be undone."""
        se = self.consume([{"item_code": ITEM, "qty": 5.0}], moved_in=155.0, already=150.0)
        self.assertEqual(se.items[0].qty, 5.0)

    def test_the_cap_applies_to_non_packaging_items_too(self):
        with self.assertRaises(frappe.ValidationError):
            self.consume([{"item_code": ITEM, "qty": 10.0}],
                         moved_in=150.0, already=150.0, packaging=False)


class TestWipInflowQuery(unittest.TestCase):
    def test_no_work_order_or_no_warehouse_asks_nothing(self):
        with patch("frappe.db.sql", side_effect=AssertionError("must not query")):
            self.assertEqual(mes_ops._wip_inflow_by_item("", WIP), {})
            self.assertEqual(mes_ops._wip_inflow_by_item(WO_NAME, ""), {})

    def test_it_sums_by_item(self):
        rows = [frappe._dict(item_code="RM20022", qty=150.0),
                frappe._dict(item_code="RM20023", qty=5.0)]
        with patch("frappe.db.sql", return_value=rows):
            self.assertEqual(mes_ops._wip_inflow_by_item(WO_NAME, WIP),
                             {"RM20022": 150.0, "RM20023": 5.0})


if __name__ == "__main__":
    unittest.main()
