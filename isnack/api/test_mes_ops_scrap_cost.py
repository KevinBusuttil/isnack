# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Rejected output has to carry a rate, or the Manufacture entry will not post.

ERPNext demands a valuation rate on every output row of a Manufacture Stock
Entry, scrap included. When all the raw materials were consumed earlier through
the LOAD button this entry has no outgoing rows of its own, so ERPNext computes
a zero cost and refuses with "Valuation Rate for the Item ... is required".
_apply_pre_consumed_cost_to_finished_item exists to supply that rate; before
this change it stopped at the finished row and left the scrap row at zero.

Rejects came off the same line out of the same materials, so they carry the
same unit cost and total value is preserved.
"""

import unittest
from unittest.mock import patch

import frappe

import isnack.api.mes_ops as mes_ops
from isnack.api.mes_ops import _apply_pre_consumed_cost_to_finished_item

WO_NAME = "MFG-WO-2026-00150"
CONSUMED_COST = 180.25          # what the LOAD-button entries already booked


class FakeStockEntry:
    def __init__(self, rows):
        self.items = rows


def output_rows(good=145.0, reject=5.0, item="SFG10001"):
    rows = [frappe._dict(item_code=item, qty=good, is_finished_item=1,
                         t_warehouse="Semi-finished - ISN")]
    if reject:
        rows.append(frappe._dict(item_code=item, qty=reject, is_scrap_item=1,
                                 t_warehouse="Rejects - ISN"))
    return rows


class ScrapCostHarness(unittest.TestCase):
    def apply(self, rows, finished_qty=145.0, consumed_cost=CONSUMED_COST, bin_rates=()):
        se = FakeStockEntry(rows)
        with patch.object(mes_ops, "_get_total_consumed_cost", return_value=consumed_cost), \
             patch("frappe.db.sql", return_value=list(bin_rates)):
            _apply_pre_consumed_cost_to_finished_item(se, WO_NAME, finished_qty)
        return se


class TestScrapRowIsValued(ScrapCostHarness):
    def test_the_scrap_row_gets_a_rate(self):
        se = self.apply(output_rows())
        scrap = next(r for r in se.items if r.get("is_scrap_item"))
        self.assertGreater(scrap.basic_rate, 0)
        self.assertEqual(scrap.set_basic_rate_manually, 1)

    def test_good_and_reject_carry_the_same_unit_cost(self):
        se = self.apply(output_rows())
        good = next(r for r in se.items if r.get("is_finished_item"))
        scrap = next(r for r in se.items if r.get("is_scrap_item"))
        self.assertAlmostEqual(good.basic_rate, scrap.basic_rate, places=9)

    def test_the_cost_is_spread_over_good_plus_reject(self):
        se = self.apply(output_rows(good=145.0, reject=5.0))
        expected = CONSUMED_COST / 150.0
        for row in se.items:
            self.assertAlmostEqual(row.basic_rate, expected, places=9)

    def test_total_value_is_preserved(self):
        se = self.apply(output_rows(good=145.0, reject=5.0))
        booked = sum(row.basic_rate * row.qty for row in se.items)
        self.assertAlmostEqual(booked, CONSUMED_COST, places=6)


class TestNoScrapIsUnchanged(ScrapCostHarness):
    """With no reject row the arithmetic must be identical to what it replaced."""

    def test_finished_row_keeps_the_good_only_rate(self):
        se = self.apply(output_rows(reject=0), finished_qty=150.0)
        self.assertAlmostEqual(se.items[0].basic_rate, CONSUMED_COST / 150.0, places=9)

    def test_remaining_material_cost_still_counts(self):
        """Rows this entry consumes itself are added to the pre-consumed total."""
        rows = output_rows(reject=0) + [
            frappe._dict(item_code="RM20022", qty=10.0, s_warehouse="EXT1-WIP - ISN")
        ]
        se = self.apply(rows, finished_qty=150.0,
                        bin_rates=[frappe._dict(item_code="RM20022",
                                                warehouse="EXT1-WIP - ISN",
                                                valuation_rate=2.0)])
        self.assertAlmostEqual(se.items[0].basic_rate, (CONSUMED_COST + 20.0) / 150.0, places=9)


class TestItStaysOutOfTheWay(ScrapCostHarness):
    def test_nothing_is_priced_when_no_cost_was_pre_consumed(self):
        se = self.apply(output_rows(), consumed_cost=0.0)
        for row in se.items:
            self.assertIsNone(row.get("basic_rate"))

    def test_nothing_is_priced_when_there_is_no_output(self):
        se = self.apply(output_rows(good=0.0, reject=0.0), finished_qty=0.0)
        for row in se.items:
            self.assertIsNone(row.get("basic_rate"))

    def test_a_scrap_only_entry_is_left_alone(self):
        """finished_qty 0 with a reject row is a total write-off. The helper
        declines it, as it always has; recording the boundary so the behaviour
        is not mistaken for the bug this change fixed."""
        rows = [frappe._dict(item_code="SFG10001", qty=5.0, is_scrap_item=1,
                             t_warehouse="Rejects - ISN")]
        se = FakeStockEntry(rows)
        with patch.object(mes_ops, "_get_total_consumed_cost", return_value=CONSUMED_COST), \
             patch("frappe.db.sql", return_value=[]):
            _apply_pre_consumed_cost_to_finished_item(se, WO_NAME, 0.0)
        self.assertIsNone(rows[0].get("basic_rate"))


if __name__ == "__main__":
    unittest.main()
