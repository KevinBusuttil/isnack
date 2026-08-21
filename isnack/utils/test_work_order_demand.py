# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for the Work Order material-demand overlay.

The scenario pinned throughout is the production case that motivated the
backport:

    Work Order  MFG-WO-2026-00026   qty 193
    BOM         BOM-FG10005-001     RM20003 at 805 kg / 1000 finished units
    ERPNext-derived requirement     193 * 805 / 1000 = 155.365 kg
    Manual requirement              147.910 kg

Every assertion here is about the *rules*: with the setting off nothing is
touched at all, and with it on the saved Work Order row wins without disturbing
the BOM-derived membership that iSnack's sub-assembly separation depends on.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from isnack.utils import work_order_demand
from isnack.utils.work_order_demand import (
    ISNACK_FIELDNAME,
    UPSTREAM_FIELDNAME,
    allow_editing_items,
    get_demand,
    is_manual_item,
    overlay_map,
    overlay_rows,
    required_qty_for,
)

WO_NAME = "MFG-WO-2026-00026"
BOM_NO = "BOM-FG10005-001"
WO_QTY = 193.0
BOM_REQUIRED = 155.365
MANUAL_REQUIRED = 147.910


class FakeRow(dict):
    """Work Order Item row; supports both attribute and mapping access."""

    def __getattr__(self, key):
        return self.get(key)


class FakeWorkOrder:
    def __init__(self, required_items=None, bom_no=BOM_NO, qty=WO_QTY, use_multi_level_bom=0, name=WO_NAME):
        self.name = name
        self.bom_no = bom_no
        self.qty = qty
        self.use_multi_level_bom = use_multi_level_bom
        self.required_items = required_items if required_items is not None else []

    def get(self, key, default=None):
        return getattr(self, key, default)


def wo_with(rm_qty=MANUAL_REQUIRED, extra_rows=()):
    rows = [FakeRow(item_code="RM20003", required_qty=rm_qty, stock_uom="Kg")]
    rows.extend(FakeRow(**r) for r in extra_rows)
    return FakeWorkOrder(required_items=rows)


class BomFixture:
    """Patches every BOM read `get_demand` performs.

    leaf        direct BOM Item rows without their own BOM
    sub         direct BOM Item rows that are sub-assemblies
    exploded    BOM Explosion Item rows (leaves of the whole tree)
    """

    def __init__(self, leaf=("RM20003", "RM20004"), sub=(), exploded=None):
        self.leaf = list(leaf)
        self.sub = list(sub)
        self.exploded = list(exploded) if exploded is not None else list(leaf)

    def get_all(self, doctype, filters=None, fields=None, **kwargs):
        if doctype == "BOM Item":
            return [{"item_code": c} for c in self.leaf + self.sub]
        if doctype == "BOM Explosion Item":
            return [{"item_code": c} for c in self.exploded]
        return []

    def bom_items_as_dict(self, bom_no, company, qty=1, fetch_exploded=0, **kwargs):
        codes = self.exploded if fetch_exploded else (self.leaf + self.sub)
        return {c: {"qty": 1.0} for c in codes}


def _get_value(doctype, name, fieldname=None, *args, **kwargs):
    """BOM company lookups and Item stock-uom lookups, the only two get_value
    calls the module makes."""
    if doctype == "Item":
        return "Nos"
    return "Test Co"


def with_demand(fixture=None, enabled=True):
    """Context stack for exercising get_demand()."""
    fixture = fixture or BomFixture()
    return [
        patch.object(work_order_demand, "allow_editing_items", return_value=enabled),
        patch("frappe.get_all", side_effect=fixture.get_all),
        patch("frappe.db.get_value", side_effect=_get_value),
        patch(
            "erpnext.manufacturing.doctype.bom.bom.get_bom_items_as_dict",
            side_effect=fixture.bom_items_as_dict,
        ),
    ]


class DemandCase(unittest.TestCase):
    def build(self, wo, fixture=None, enabled=True):
        patches = with_demand(fixture, enabled)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return get_demand(wo)


class TestAllowEditingItems(unittest.TestCase):
    """Setting resolution: upstream field first, iSnack Custom Field as fallback."""

    def _meta(self, *present):
        meta = MagicMock()
        meta.has_field.side_effect = lambda f: f in present
        return meta

    @patch("frappe.db.get_single_value", return_value=0)
    @patch("frappe.get_meta")
    def test_off_by_default(self, mock_meta, mock_single):
        mock_meta.return_value = self._meta(ISNACK_FIELDNAME)
        self.assertFalse(allow_editing_items())

    @patch("frappe.db.get_single_value", return_value=None)
    @patch("frappe.get_meta")
    def test_off_when_never_saved(self, mock_meta, mock_single):
        """An untouched Single has no stored value at all — still off."""
        mock_meta.return_value = self._meta(ISNACK_FIELDNAME)
        self.assertFalse(allow_editing_items())

    @patch("frappe.db.get_single_value", return_value=1)
    @patch("frappe.get_meta")
    def test_on_via_isnack_custom_field(self, mock_meta, mock_single):
        mock_meta.return_value = self._meta(ISNACK_FIELDNAME)
        self.assertTrue(allow_editing_items())
        mock_single.assert_called_once_with("Manufacturing Settings", ISNACK_FIELDNAME)

    @patch("frappe.get_meta")
    def test_prefers_upstream_field_when_present(self, mock_meta):
        """After an ERPNext upgrade the real field answers first."""
        mock_meta.return_value = self._meta(UPSTREAM_FIELDNAME, ISNACK_FIELDNAME)
        with patch("frappe.db.get_single_value", return_value=1) as mock_single:
            self.assertTrue(allow_editing_items())
        self.assertEqual(mock_single.call_args_list[0][0][1], UPSTREAM_FIELDNAME)

    @patch("frappe.get_meta")
    def test_isnack_field_still_honoured_after_upgrade(self, mock_meta):
        """An upgrade must not silently switch the feature off."""
        mock_meta.return_value = self._meta(UPSTREAM_FIELDNAME, ISNACK_FIELDNAME)
        values = {UPSTREAM_FIELDNAME: 0, ISNACK_FIELDNAME: 1}
        with patch("frappe.db.get_single_value", side_effect=lambda dt, f: values[f]):
            self.assertTrue(allow_editing_items())

    @patch("frappe.get_meta", side_effect=Exception("no such doctype"))
    def test_broken_read_is_off(self, _meta):
        self.assertFalse(allow_editing_items())

    @patch("frappe.db.get_single_value")
    @patch("frappe.get_meta")
    def test_absent_field_is_never_read(self, mock_meta, mock_single):
        """Manufacturing Settings without either field must not raise."""
        mock_meta.return_value = self._meta()
        self.assertFalse(allow_editing_items())
        mock_single.assert_not_called()


class TestGetDemand(DemandCase):
    def test_disabled_when_setting_off(self):
        demand = self.build(wo_with(), enabled=False)
        self.assertFalse(demand.enabled)
        self.assertEqual(demand.required, {})

    def test_disabled_when_table_empty(self):
        """An empty table is repopulated from the BOM; it must not erase demand."""
        demand = self.build(FakeWorkOrder(required_items=[]))
        self.assertFalse(demand.enabled)

    def test_disabled_without_bom(self):
        demand = self.build(FakeWorkOrder(required_items=[FakeRow(item_code="X", required_qty=1)], bom_no=None))
        self.assertFalse(demand.enabled)

    def test_collects_saved_quantities(self):
        demand = self.build(wo_with())
        self.assertTrue(demand.enabled)
        self.assertEqual(demand.required["RM20003"], MANUAL_REQUIRED)
        self.assertEqual(demand.uoms["RM20003"], "Kg")

    def test_sums_duplicate_rows_for_one_item(self):
        wo = FakeWorkOrder(required_items=[
            FakeRow(item_code="RM20003", required_qty=100.0),
            FakeRow(item_code="RM20003", required_qty=47.910),
        ])
        demand = self.build(wo)
        self.assertAlmostEqual(demand.required["RM20003"], MANUAL_REQUIRED, places=6)

    def test_manual_row_is_the_only_non_bom_row(self):
        wo = wo_with(extra_rows=[{"item_code": "RM99999", "required_qty": 5.0}])
        demand = self.build(wo, BomFixture(leaf=("RM20003",), exploded=("RM20003", "SFGRAW1")))
        self.assertEqual(demand.manual, {"RM99999"})

    def test_exploded_sub_assembly_raw_material_is_never_manual(self):
        """The parent/SFG separation: SFGRAW1 belongs to the child WO, not here."""
        wo = wo_with(extra_rows=[{"item_code": "SFGRAW1", "required_qty": 12.0}])
        demand = self.build(wo, BomFixture(leaf=("RM20003",), sub=("SFG10001",), exploded=("RM20003", "SFGRAW1")))
        self.assertEqual(demand.manual, set())

    def test_covered_follows_use_multi_level_bom(self):
        fixture = BomFixture(leaf=("RM20003",), sub=("SFG10001",), exploded=("RM20003", "SFGRAW1"))
        single = self.build(wo_with(), fixture)
        self.assertEqual(single.covered, {"RM20003", "SFG10001"})

    def test_qty_for_reports_deleted_row_as_zero(self):
        wo = FakeWorkOrder(required_items=[FakeRow(item_code="RM20004", required_qty=3.0)])
        demand = self.build(wo)
        self.assertEqual(demand.qty_for("RM20003"), 0.0)

    def test_qty_for_is_silent_outside_covered_scope(self):
        wo = wo_with()
        demand = self.build(wo, BomFixture(leaf=("RM20003",), exploded=("RM20003", "SFGRAW1")))
        self.assertIsNone(demand.qty_for("SFGRAW1"))


class TestOverlayMap(DemandCase):
    def base(self):
        return {
            "RM20003": {"uom": "Kg", "qty": BOM_REQUIRED},
            "RM20004": {"uom": "Kg", "qty": 20.0},
        }

    def test_setting_off_returns_input_untouched(self):
        base = self.base()
        out = self.build_overlay(wo_with(), base, enabled=False)
        self.assertIs(out, base)
        self.assertEqual(out["RM20003"]["qty"], BOM_REQUIRED)

    def build_overlay(self, wo, base, fixture=None, enabled=True, **kwargs):
        patches = with_demand(fixture, enabled)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return overlay_map(wo, base, **kwargs)

    def test_manual_quantity_replaces_bom_quantity(self):
        out = self.build_overlay(wo_with(), self.base())
        self.assertEqual(out["RM20003"]["qty"], MANUAL_REQUIRED)
        self.assertEqual(out["RM20003"]["uom"], "Kg")

    def test_untouched_rows_keep_their_bom_quantity(self):
        wo = wo_with(extra_rows=[{"item_code": "RM20004", "required_qty": 20.0}])
        out = self.build_overlay(wo, self.base())
        self.assertEqual(out["RM20004"]["qty"], 20.0)

    def test_deleted_row_removes_demand(self):
        wo = FakeWorkOrder(required_items=[FakeRow(item_code="RM20004", required_qty=20.0)])
        out = self.build_overlay(wo, self.base())
        self.assertNotIn("RM20003", out)

    def test_manual_row_is_added(self):
        wo = wo_with(extra_rows=[{"item_code": "RM99999", "required_qty": 5.0}])
        out = self.build_overlay(wo, self.base(), BomFixture(leaf=("RM20003", "RM20004")))
        self.assertEqual(out["RM99999"]["qty"], 5.0)

    def test_out_of_scope_bom_row_is_left_alone(self):
        """A single-level WO's exploded map still carries the child's raws."""
        base = dict(self.base())
        base["SFGRAW1"] = {"uom": "Kg", "qty": 40.0}
        out = self.build_overlay(wo_with(), base, BomFixture(leaf=("RM20003", "RM20004"), exploded=("RM20003", "RM20004", "SFGRAW1")))
        self.assertEqual(out["SFGRAW1"]["qty"], 40.0)

    def test_scale_rescales_the_saved_requirement(self):
        out = self.build_overlay(wo_with(), self.base(), scale=0.5)
        self.assertAlmostEqual(out["RM20003"]["qty"], MANUAL_REQUIRED / 2, places=6)

    def test_does_not_mutate_the_input_map(self):
        base = self.base()
        self.build_overlay(wo_with(), base)
        self.assertEqual(base["RM20003"]["qty"], BOM_REQUIRED)


class TestOverlayRows(DemandCase):
    def rows(self):
        return [
            {"item_code": "RM20003", "qty": BOM_REQUIRED, "uom": "Kg"},
            {"item_code": "RM20004", "qty": 20.0, "uom": "Kg"},
        ]

    def run_overlay(self, wo, rows, fixture=None, enabled=True, **kwargs):
        patches = with_demand(fixture, enabled)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return overlay_rows(wo, rows, **kwargs)

    def test_setting_off_returns_input_untouched(self):
        rows = self.rows()
        self.assertIs(self.run_overlay(wo_with(), rows, enabled=False), rows)

    def test_manual_quantity_wins(self):
        out = self.run_overlay(wo_with(), self.rows())
        by_code = {r["item_code"]: r for r in out}
        self.assertEqual(by_code["RM20003"]["qty"], MANUAL_REQUIRED)

    def test_scaled_to_a_partial_production_quantity(self):
        """A close for half the planned output needs half the planned material."""
        out = self.run_overlay(wo_with(), self.rows(), scale=0.5)
        by_code = {r["item_code"]: r for r in out}
        self.assertAlmostEqual(by_code["RM20003"]["qty"], MANUAL_REQUIRED / 2, places=6)

    def test_deleted_row_drops_out(self):
        wo = FakeWorkOrder(required_items=[FakeRow(item_code="RM20004", required_qty=20.0)])
        out = self.run_overlay(wo, self.rows())
        self.assertNotIn("RM20003", [r["item_code"] for r in out])

    def test_manual_row_appended_with_uom(self):
        wo = wo_with(extra_rows=[{"item_code": "RM99999", "required_qty": 5.0}])
        out = self.run_overlay(wo, self.rows(), BomFixture(leaf=("RM20003", "RM20004")))
        added = [r for r in out if r["item_code"] == "RM99999"][0]
        self.assertEqual(added["qty"], 5.0)
        self.assertEqual(added["uom"], "Nos")

    def test_custom_qty_key(self):
        rows = [{"item_code": "RM20003", "required": BOM_REQUIRED, "uom": "Kg"}]
        out = self.run_overlay(wo_with(), rows, qty_key="required")
        self.assertEqual(out[0]["required"], MANUAL_REQUIRED)

    def test_does_not_mutate_input_rows(self):
        rows = self.rows()
        self.run_overlay(wo_with(), rows)
        self.assertEqual(rows[0]["qty"], BOM_REQUIRED)


class TestScalarHelpers(DemandCase):
    def call(self, fn, *args, fixture=None, enabled=True, **kwargs):
        patches = with_demand(fixture, enabled)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return fn(*args, **kwargs)

    def test_required_qty_for_returns_saved_value(self):
        self.assertEqual(self.call(required_qty_for, wo_with(), "RM20003"), MANUAL_REQUIRED)

    def test_required_qty_for_is_none_when_setting_off(self):
        self.assertIsNone(self.call(required_qty_for, wo_with(), "RM20003", enabled=False))

    def test_required_qty_for_is_none_for_deleted_row(self):
        """Consumption ceilings fall back to the BOM rather than blocking at 0."""
        wo = FakeWorkOrder(required_items=[FakeRow(item_code="RM20004", required_qty=1.0)])
        self.assertIsNone(self.call(required_qty_for, wo, "RM20003"))

    def test_required_qty_for_scales(self):
        self.assertAlmostEqual(
            self.call(required_qty_for, wo_with(), "RM20003", scale=2.0), MANUAL_REQUIRED * 2, places=6
        )

    def test_is_manual_item(self):
        wo = wo_with(extra_rows=[{"item_code": "RM99999", "required_qty": 5.0}])
        fixture = BomFixture(leaf=("RM20003",), exploded=("RM20003", "SFGRAW1"))
        self.assertTrue(self.call(is_manual_item, wo, "RM99999", fixture=fixture))

    def test_bom_item_is_not_manual(self):
        wo = wo_with(extra_rows=[{"item_code": "RM99999", "required_qty": 5.0}])
        fixture = BomFixture(leaf=("RM20003",), exploded=("RM20003", "SFGRAW1"))
        self.assertFalse(self.call(is_manual_item, wo, "RM20003", fixture=fixture))
        self.assertFalse(self.call(is_manual_item, wo, "SFGRAW1", fixture=fixture))

    def test_is_manual_item_false_when_setting_off(self):
        wo = wo_with(extra_rows=[{"item_code": "RM99999", "required_qty": 5.0}])
        self.assertFalse(self.call(is_manual_item, wo, "RM99999", enabled=False))


class TestCoveredIsLazy(DemandCase):
    """The expensive BOM read only happens when a row is actually missing."""

    def _stack(self, fixture, spy):
        return [
            patch.object(work_order_demand, "allow_editing_items", return_value=True),
            patch("frappe.get_all", side_effect=fixture.get_all),
            patch("frappe.db.get_value", side_effect=_get_value),
            patch("erpnext.manufacturing.doctype.bom.bom.get_bom_items_as_dict", side_effect=spy),
        ]

    def _run(self, wo, base, fixture):
        calls = []

        def spy(*args, **kwargs):
            calls.append(args)
            return fixture.bom_items_as_dict(*args, **kwargs)

        patches = self._stack(fixture, spy)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        overlay_map(wo, base)
        return calls

    def test_not_read_when_every_row_is_present(self):
        base = {"RM20003": {"uom": "Kg", "qty": BOM_REQUIRED}}
        calls = self._run(wo_with(), base, BomFixture(leaf=("RM20003",)))
        self.assertEqual(calls, [])

    def test_read_once_when_a_row_is_missing(self):
        base = {
            "RM20003": {"uom": "Kg", "qty": BOM_REQUIRED},
            "RM20004": {"uom": "Kg", "qty": 20.0},
        }
        calls = self._run(wo_with(), base, BomFixture(leaf=("RM20003", "RM20004")))
        self.assertEqual(len(calls), 1)


class TestCoveredScopeFallback(DemandCase):
    def test_bom_read_failure_falls_back_to_raw_tables(self):
        """A failed BOM read must not turn into wrongly-deleted demand."""
        fixture = BomFixture(leaf=("RM20003", "RM20004"))
        patches = [
            patch.object(work_order_demand, "allow_editing_items", return_value=True),
            patch("frappe.get_all", side_effect=fixture.get_all),
            patch("frappe.db.get_value", side_effect=_get_value),
            patch("frappe.log_error"),
            patch(
                "erpnext.manufacturing.doctype.bom.bom.get_bom_items_as_dict",
                side_effect=Exception("boom"),
            ),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        demand = get_demand(wo_with())
        self.assertEqual(demand.covered, {"RM20003", "RM20004"})


if __name__ == "__main__":
    unittest.main()
