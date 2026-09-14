# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""A hub Work Order consumes its sub-assemblies, never their raw materials.

ERPNext clears use_multi_level_bom on a finished-good Work Order only when its
Production Plan carries sub-assembly rows. A planner who skips "Get Sub Assembly
Items" leaves the plan line's "Include Exploded Items" — ticked by default — to
decide, and the Work Order's required items come out as the raw materials of the
semi-finished goods instead of the semi-finished goods themselves. The Operator
Hub cannot end such an order without a Production Manager override, and cannot
close it at all.

Isolated in scenario T10: four plans for FG10011 x 300, identical but for that
one button.
"""

import unittest
from unittest.mock import patch

import frappe

import isnack.api.mes_ops as mes_ops
from isnack.api.mes_ops import _bom_has_sub_assemblies, _force_single_level_bom

FG_BOM = "BOM-FG10011-002"      # SFG10001 + SFG10002 + film + cartons
SFG_BOM = "BOM-SFG10001-001"    # corn grits + water, no sub-assemblies


class FakeWorkOrder:
    def __init__(self, bom_no=FG_BOM, use_multi_level_bom=1):
        self.name = "MFG-WO-2026-00079"
        self.bom_no = bom_no
        self.use_multi_level_bom = use_multi_level_bom
        self.rebuilt = 0

    def set_required_items(self):
        self.rebuilt += 1


class TestBomHasSubAssemblies(unittest.TestCase):
    def test_a_bom_with_a_sub_assembly_row(self):
        with patch("frappe.db.exists", return_value="BOM Item-x") as ex:
            self.assertTrue(_bom_has_sub_assemblies(FG_BOM))
        self.assertEqual(ex.call_args[0][1], {"parent": FG_BOM, "bom_no": ["!=", ""]})

    def test_a_bom_of_raw_materials_only(self):
        with patch("frappe.db.exists", return_value=None):
            self.assertFalse(_bom_has_sub_assemblies(SFG_BOM))

    def test_no_bom_at_all(self):
        with patch("frappe.db.exists", side_effect=AssertionError("must not query")):
            self.assertFalse(_bom_has_sub_assemblies(None))
            self.assertFalse(_bom_has_sub_assemblies(""))


class TestForceSingleLevelBom(unittest.TestCase):
    def apply(self, doc, has_subs=True):
        with patch.object(mes_ops, "_bom_has_sub_assemblies", return_value=has_subs):
            _force_single_level_bom(doc)
        return doc

    def test_the_flag_is_cleared_and_the_table_rebuilt(self):
        doc = self.apply(FakeWorkOrder(use_multi_level_bom=1))
        self.assertEqual(doc.use_multi_level_bom, 0)
        self.assertEqual(doc.rebuilt, 1)

    def test_a_single_level_bom_is_left_alone(self):
        doc = self.apply(FakeWorkOrder(bom_no=SFG_BOM, use_multi_level_bom=1), has_subs=False)
        self.assertEqual(doc.use_multi_level_bom, 1)
        self.assertEqual(doc.rebuilt, 0)

    def test_an_order_already_correct_is_not_rebuilt(self):
        """The rebuild only fires on the 1 -> 0 transition, so a planner's later
        edits to required_items are never clobbered by a re-save."""
        doc = self.apply(FakeWorkOrder(use_multi_level_bom=0))
        self.assertEqual(doc.rebuilt, 0)

    def test_it_is_idempotent_across_saves(self):
        doc = FakeWorkOrder(use_multi_level_bom=1)
        self.apply(doc)
        self.apply(doc)
        self.apply(doc)
        self.assertEqual(doc.rebuilt, 1)

    def test_a_failed_rebuild_still_clears_the_flag(self):
        class Broken(FakeWorkOrder):
            def set_required_items(self):
                raise ValueError("boom")

        doc = Broken()
        with patch.object(mes_ops, "_bom_has_sub_assemblies", return_value=True), \
             patch("frappe.log_error") as logged:
            _force_single_level_bom(doc)      # must not raise: never block a save
        self.assertEqual(doc.use_multi_level_bom, 0)
        self.assertTrue(logged.called)


if __name__ == "__main__":
    unittest.main()
