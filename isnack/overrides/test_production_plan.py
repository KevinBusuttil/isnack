# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""A Production Plan must not be submitted without the sub-assembly rows it needs.

ERPNext decides a finished-good Work Order's BOM level from this one table:

    if self.sub_assembly_items:
        item["use_multi_level_bom"] = 0

With it empty the flag falls through from the plan line's "Include Exploded
Items" — ticked by default — and the loop that creates the semi-finished Work
Orders iterates that same table, so none are created at all. The planner is
left with one finished-good Work Order requiring semi-finished goods that
nothing is scheduled to make.

Pressing "Get Sub Assembly Items" is what fills the table, and missing that one
button is the whole failure. It reached the client once, on MFG-PP-2026-00033,
abandoned at zero produced.
"""

import unittest
from unittest.mock import patch

import frappe

import isnack.overrides.production_plan as pp_override
from isnack.overrides.production_plan import CustomProductionPlan

FG_BOM = "BOM-FG10011-002"      # SFG10001 + SFG10002 + film + cartons
SFG_BOM = "BOM-SFG10001-001"    # corn grits + water, no sub-assemblies


def plan(po_items, sub_assembly_items=(), skip_available=0, split_ticked=1, name="MFG-PP-TEST-0001"):
    doc = CustomProductionPlan.__new__(CustomProductionPlan)
    doc.name = name
    doc.po_items = [frappe._dict(r) for r in po_items]
    doc.sub_assembly_items = [frappe._dict(r) for r in sub_assembly_items]
    doc.skip_available_sub_assembly_item = skip_available
    doc.custom_split_sub_assembly_items = split_ticked
    return doc


def fg_line(item_code="FG10011", bom_no=FG_BOM):
    return {"item_code": item_code, "bom_no": bom_no, "planned_qty": 300}


def sfg_line(item_code="SFG10001", bom_no=SFG_BOM):
    return {"item_code": item_code, "bom_no": bom_no, "planned_qty": 150}


class GuardHarness(unittest.TestCase):
    def check(self, doc, boms_with_subs=(FG_BOM,), recomputed=None):
        """Run the guard. `recomputed` is what a fresh calculation would return,
        used only on the skip-available path; None makes it raise."""
        def has_subs(bom_no):
            return bom_no in boms_with_subs

        def compute(manufacturing_type=None, quiet=False):
            if recomputed is None:
                raise ValueError("cannot compute")
            return list(recomputed)

        with patch.object(pp_override, "_bom_has_sub_assemblies", side_effect=has_subs), \
             patch.object(pp_override, "_sub_assembly_items_of",
                          return_value=["SFG10001", "SFG10002"]), \
             patch.object(CustomProductionPlan, "compute_sub_assembly_rows", side_effect=compute), \
             patch("frappe.log_error"):
            doc.validate_sub_assembly_items_fetched()

    def assertBlocked(self, doc, **kw):
        with self.assertRaises(frappe.ValidationError):
            self.check(doc, **kw)

    def assertAllowed(self, doc, **kw):
        self.check(doc, **kw)


class TestTheFailureIsCaught(GuardHarness):
    def test_the_button_was_never_pressed(self):
        self.assertBlocked(plan([fg_line()]))

    def test_the_message_names_the_product_and_what_it_needs(self):
        try:
            self.check(plan([fg_line()]))
        except frappe.ValidationError as e:
            msg = str(e)
        else:
            self.fail("expected a ValidationError")
        self.assertIn("FG10011", msg)
        self.assertIn("SFG10001", msg)
        self.assertIn("Get Sub Assembly Items", msg)

    def test_it_does_not_depend_on_the_split_checkbox(self):
        """The checkbox only changes how the rows are built. A planner who
        misses it as well as the button hits the same failure."""
        self.assertBlocked(plan([fg_line()], split_ticked=0))

    def test_one_multi_level_line_among_several_is_enough(self):
        self.assertBlocked(plan([sfg_line(), fg_line()]))


class TestLegitimateEmptyTables(GuardHarness):
    def test_a_plan_whose_boms_have_no_sub_assemblies(self):
        """FG10001-FG10010 are single-level; their table is empty and always
        will be."""
        self.assertAllowed(plan([sfg_line()]), boms_with_subs=())

    def test_the_rows_are_already_there(self):
        self.assertAllowed(plan([fg_line()], sub_assembly_items=[{"production_item": "SFG10001"}]))

    def test_skip_available_with_the_stock_already_made(self):
        """The button was pressed and legitimately returned nothing, because
        there is enough semi-finished stock to cover the plan."""
        self.assertAllowed(plan([fg_line()], skip_available=1), recomputed=[])

    def test_a_line_with_no_bom_is_not_this_guard_s_business(self):
        self.assertAllowed(plan([{"item_code": "FG10011", "bom_no": None, "planned_qty": 300}]),
                           boms_with_subs=())


class TestSkipAvailableStillCatchesTheMissedButton(GuardHarness):
    def test_rows_come_back_so_the_button_was_never_pressed(self):
        self.assertBlocked(plan([fg_line()], skip_available=1),
                           recomputed=[{"production_item": "SFG10001"}])

    def test_a_recompute_that_fails_does_not_wave_the_plan_through(self):
        """If the check cannot prove the empty table is legitimate, it blocks:
        a plan nobody can fulfil costs more than a plan resubmitted."""
        self.assertBlocked(plan([fg_line()], skip_available=1), recomputed=None)


class TestComputeIsSeparateFromStoring(unittest.TestCase):
    """get_sub_assembly_items stores what compute_sub_assembly_rows returns, so
    the guard's second opinion can never disagree with what the button did."""

    def test_the_button_stores_the_computed_rows_in_order(self):
        doc = plan([fg_line()])
        rows = [frappe._dict(production_item="SFG10001"), frappe._dict(production_item="SFG10002")]
        appended = []
        doc.append = lambda field, row: appended.append((field, row))
        doc.set_default_supplier_for_subcontracting_order = lambda: None

        with patch.object(CustomProductionPlan, "compute_sub_assembly_rows", return_value=rows):
            CustomProductionPlan.get_sub_assembly_items(doc)

        self.assertEqual(doc.sub_assembly_items, [])
        self.assertEqual([f for f, _ in appended], ["sub_assembly_items"] * 2)
        self.assertEqual([r.idx for _, r in appended], [1, 2])


if __name__ == "__main__":
    unittest.main()
