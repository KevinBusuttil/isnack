# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Operator Hub / MES behaviour when Work Order quantities are editable.

Each BOM read in ``mes_ops`` was classified before being changed:

    planned demand for THIS Work Order  -> follows the saved required_items
        _planned_items_for_wo (requestable items, End WO summary, Close
        Production and _close_single_wo consumption), get_materials_snapshot,
        get_manual_load_item_context, the over-consumption ceiling

    structural / business-rule BOM check -> stays BOM-based
        _validate_item_in_bom's DIRECT BOM Item membership test, which is what
        stops a parent finished-good Work Order from consuming raw materials
        belonging to a separate semi-finished Work Order. The single addition is
        a row the planner added that the BOM has never mentioned at all.

    intentional BOM semantics            -> untouched
        get_sfg_components_for_wo, _get_bom_items_for_quantity itself, the
        packaging BOM item list.

Numbers throughout are the production case: MFG-WO-2026-00026, qty 193, RM20003
at 805 kg / 1000 units, so the BOM asks 155.365 kg and the planner asked 147.910.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

import isnack.api.mes_ops as mes_ops
from isnack.api.mes_ops import (
    _planned_items_for_wo,
    _planned_required_qty,
    _validate_item_in_bom,
    get_manual_load_item_context,
)

WO_NAME = "MFG-WO-2026-00026"
BOM_NO = "BOM-FG10005-001"
WO_QTY = 193.0
RM = "RM20003"
BOM_REQUIRED = 155.365
MANUAL_REQUIRED = 147.910


class FakeWorkOrder:
    def __init__(self, required_items=None, qty=WO_QTY, use_multi_level_bom=0):
        self.name = WO_NAME
        self.bom_no = BOM_NO
        self.qty = qty
        self.company = "Test Co"
        self.use_multi_level_bom = use_multi_level_bom
        self.required_items = required_items if required_items is not None else []

    def get(self, key, default=None):
        return getattr(self, key, default)


def wo_rows(rm_qty=MANUAL_REQUIRED, extra=()):
    rows = [frappe._dict(item_code=RM, required_qty=rm_qty, stock_uom="Kg")]
    rows.extend(frappe._dict(**r) for r in extra)
    return rows


class DemandHarness(unittest.TestCase):
    def harness(self, enabled=True, leaf=(RM,), sub=(), exploded=None):
        exploded = list(exploded) if exploded is not None else list(leaf)

        def fake_get_all(doctype, filters=None, fields=None, **kwargs):
            if doctype == "BOM Item":
                return [{"item_code": c} for c in list(leaf) + list(sub)]
            if doctype == "BOM Explosion Item":
                return [{"item_code": c} for c in exploded]
            return []

        patches = [
            patch.object(mes_ops.work_order_demand, "allow_editing_items", return_value=enabled),
            patch("frappe.get_all", side_effect=fake_get_all),
            patch(
                "erpnext.manufacturing.doctype.bom.bom.get_bom_items_as_dict",
                side_effect=lambda bom_no, company, qty=1, fetch_exploded=0, **k: {
                    c: {"qty": 1.0} for c in (exploded if fetch_exploded else list(leaf) + list(sub))
                },
            ),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])


class TestPlannedItemsForWo(DemandHarness):
    """The planning list every consumption path is built from."""

    def bom_items(self, qty):
        factor = qty / WO_QTY
        return [
            {"item_code": RM, "qty": BOM_REQUIRED * factor, "uom": "Kg"},
            {"item_code": "RM20004", "qty": 20.0 * factor, "uom": "Kg"},
        ]

    def invoke(self, wo, qty, enabled=True, **kwargs):
        self.harness(enabled=enabled, leaf=kwargs.pop("leaf", (RM, "RM20004")), **kwargs)
        with patch.object(
            mes_ops, "_get_bom_items_for_quantity", side_effect=lambda b, q, exploded=True: self.bom_items(q)
        ):
            with patch("frappe.db.get_value", return_value="Kg"):
                return {r["item_code"]: r for r in _planned_items_for_wo(wo, qty)}

    def test_setting_off_is_pure_bom(self):
        out = self.invoke(FakeWorkOrder(wo_rows()), WO_QTY, enabled=False)
        self.assertAlmostEqual(out[RM]["qty"], BOM_REQUIRED, places=6)

    def test_full_quantity_uses_the_saved_requirement(self):
        out = self.invoke(FakeWorkOrder(wo_rows()), WO_QTY)
        self.assertAlmostEqual(out[RM]["qty"], MANUAL_REQUIRED, places=6)

    def test_partial_close_scales_the_saved_requirement(self):
        """Closing 96.5 of 193 units needs half of 147.910, not half of 155.365."""
        out = self.invoke(FakeWorkOrder(wo_rows()), WO_QTY / 2)
        self.assertAlmostEqual(out[RM]["qty"], MANUAL_REQUIRED / 2, places=6)

    def test_rows_left_alone_keep_their_quantity(self):
        """Only the edited row moves; RM20004 still carries its BOM figure."""
        wo = FakeWorkOrder(wo_rows(extra=[{"item_code": "RM20004", "required_qty": 20.0}]))
        out = self.invoke(wo, WO_QTY)
        self.assertAlmostEqual(out["RM20004"]["qty"], 20.0, places=6)
        self.assertAlmostEqual(out[RM]["qty"], MANUAL_REQUIRED, places=6)

    def test_deleted_row_is_not_consumed(self):
        wo = FakeWorkOrder([frappe._dict(item_code="RM20004", required_qty=20.0)])
        out = self.invoke(wo, WO_QTY)
        self.assertNotIn(RM, out)

    def test_manual_row_is_consumed(self):
        wo = FakeWorkOrder(wo_rows(extra=[{"item_code": "RM99999", "required_qty": 5.0}]))
        out = self.invoke(wo, WO_QTY)
        self.assertEqual(out["RM99999"]["qty"], 5.0)

    def test_zero_qty_work_order_falls_back_to_the_bom(self):
        """No sane scale factor exists; never divide by zero."""
        wo = FakeWorkOrder(wo_rows(), qty=0)
        out = self.invoke(wo, 10.0)
        self.assertIn(RM, out)

    def test_empty_table_falls_back_to_the_bom(self):
        out = self.invoke(FakeWorkOrder([]), WO_QTY)
        self.assertAlmostEqual(out[RM]["qty"], BOM_REQUIRED, places=6)


class TestValidateItemInBom(DemandHarness):
    """Structural membership: BOM-based, plus hand-added rows only."""

    def invoke(self, item_code, in_bom, wo, enabled=True, **kwargs):
        self.harness(enabled=enabled, **kwargs)
        with patch("frappe.db.get_value", return_value=BOM_NO):
            with patch("frappe.db.exists", return_value=1 if in_bom else 0):
                with patch("frappe.get_doc", return_value=wo):
                    return _validate_item_in_bom(WO_NAME, item_code)

    def test_bom_item_is_accepted(self):
        ok, _msg = self.invoke(RM, True, FakeWorkOrder(wo_rows()))
        self.assertTrue(ok)

    def test_unknown_item_is_rejected(self):
        ok, msg = self.invoke("RM77777", False, FakeWorkOrder(wo_rows()))
        self.assertFalse(ok)
        self.assertIn("not in BOM", msg)

    def test_hand_added_row_is_accepted(self):
        wo = FakeWorkOrder(wo_rows(extra=[{"item_code": "RM99999", "required_qty": 5.0}]))
        ok, _msg = self.invoke("RM99999", False, wo, leaf=(RM,))
        self.assertTrue(ok)

    def test_hand_added_row_is_rejected_while_setting_is_off(self):
        wo = FakeWorkOrder(wo_rows(extra=[{"item_code": "RM99999", "required_qty": 5.0}]))
        ok, _msg = self.invoke("RM99999", False, wo, enabled=False, leaf=(RM,))
        self.assertFalse(ok)

    def test_sub_assembly_raw_material_is_still_rejected(self):
        """The parent/SFG separation must survive the relaxation."""
        wo = FakeWorkOrder(wo_rows(extra=[{"item_code": "SFGRAW1", "required_qty": 19.3}]))
        ok, msg = self.invoke("SFGRAW1", False, wo, leaf=(RM,), sub=("SFG10001",), exploded=(RM, "SFGRAW1"))
        self.assertFalse(ok)
        self.assertIn("not in BOM", msg)

    def test_work_order_without_bom_is_rejected(self):
        with patch("frappe.db.get_value", return_value=None):
            ok, msg = _validate_item_in_bom(WO_NAME, RM)
        self.assertFalse(ok)
        self.assertIn("no BOM", msg)


class TestOverConsumptionBaseline(DemandHarness):
    """The threshold ceiling: Work Order first, BOM as the fallback."""

    def invoke(self, item_code, wo, enabled=True, **kwargs):
        self.harness(enabled=enabled, **kwargs)
        with patch("frappe.get_doc", return_value=wo):
            return _planned_required_qty(WO_NAME, item_code)

    def test_uses_the_saved_requirement(self):
        self.assertAlmostEqual(
            self.invoke(RM, FakeWorkOrder(wo_rows())), MANUAL_REQUIRED, places=6
        )

    def test_none_while_setting_is_off(self):
        self.assertIsNone(self.invoke(RM, FakeWorkOrder(wo_rows()), enabled=False))

    def test_none_for_a_deleted_row_so_the_bom_ceiling_survives(self):
        """A planning edit must never hard-block an operator mid-shift."""
        wo = FakeWorkOrder([frappe._dict(item_code="RM20004", required_qty=20.0)])
        self.assertIsNone(self.invoke(RM, wo, leaf=(RM, "RM20004")))

    def test_hand_added_row_gets_a_ceiling_of_its_own(self):
        wo = FakeWorkOrder(wo_rows(extra=[{"item_code": "RM99999", "required_qty": 5.0}]))
        self.assertEqual(self.invoke("RM99999", wo, leaf=(RM,)), 5.0)


class TestManualLoadItemContext(DemandHarness):
    """The Manual Load dialog's Required / Remaining figures."""

    def invoke(self, wo, enabled=True, consumed=0.0):
        self.harness(enabled=enabled)
        bom = MagicMock()
        bom.get.return_value = 1000.0
        bom.items = [frappe._dict(item_code=RM, qty=805.0)]

        def fake_get_doc(doctype, name=None, *args, **kwargs):
            return wo if doctype == "Work Order" else bom

        with patch.object(mes_ops, "_require_roles"):
            with patch("frappe.get_doc", side_effect=fake_get_doc):
                with patch("frappe.db.get_value", return_value="Kg"):
                    with patch("frappe.db.sql", return_value=[[consumed]]):
                        return get_manual_load_item_context(WO_NAME, RM)

    def test_shows_the_saved_requirement(self):
        out = self.invoke(FakeWorkOrder(wo_rows()))
        self.assertAlmostEqual(out["required_qty"], MANUAL_REQUIRED, places=6)

    def test_remaining_follows_the_saved_requirement(self):
        out = self.invoke(FakeWorkOrder(wo_rows()), consumed=100.0)
        self.assertAlmostEqual(out["remaining_qty"], 47.910, places=6)

    def test_setting_off_shows_the_bom_requirement(self):
        out = self.invoke(FakeWorkOrder(wo_rows()), enabled=False)
        self.assertAlmostEqual(out["required_qty"], BOM_REQUIRED, places=6)


class TestMaterialsSnapshot(DemandHarness):
    """The Operator Hub materials table."""

    def invoke(self, wo, enabled=True):
        self.harness(enabled=enabled)
        bom = MagicMock()
        bom.get.return_value = 1000.0
        bom.items = [frappe._dict(item_code=RM, item_name="Rice Flour", qty=805.0, stock_uom="Kg", uom="Kg")]

        def fake_get_doc(doctype, name=None, *args, **kwargs):
            return wo if doctype == "Work Order" else bom

        with patch.object(mes_ops, "_require_roles"):
            with patch("frappe.get_doc", side_effect=fake_get_doc):
                with patch("frappe.db.get_value", return_value="Kg"):
                    with patch("frappe.db.sql", return_value=[]):
                        out = mes_ops.get_materials_snapshot(WO_NAME)
        return {r["item_code"]: r for r in out["rows"]}

    def test_required_follows_the_work_order(self):
        rows = self.invoke(FakeWorkOrder(wo_rows()))
        self.assertAlmostEqual(rows[RM]["required"], MANUAL_REQUIRED, places=6)
        self.assertAlmostEqual(rows[RM]["remain"], MANUAL_REQUIRED, places=6)

    def test_setting_off_shows_the_bom_requirement(self):
        rows = self.invoke(FakeWorkOrder(wo_rows()), enabled=False)
        self.assertAlmostEqual(rows[RM]["required"], BOM_REQUIRED, places=6)

    def test_hand_added_row_appears_with_a_name(self):
        wo = FakeWorkOrder(wo_rows(extra=[{"item_code": "RM99999", "required_qty": 5.0}]))
        rows = self.invoke(wo)
        self.assertIn("RM99999", rows)
        self.assertEqual(rows["RM99999"]["transferred"], 0.0)
        self.assertEqual(rows["RM99999"]["consumed"], 0.0)


class TestEndWoSfgRequirement(DemandHarness):
    """The End WO dialog must not show two requirements for one item."""

    SFG = "SFG10001"

    def invoke(self, wo, enabled=True):
        self.harness(enabled=enabled, leaf=(RM,), sub=(self.SFG,), exploded=(RM, "SFGRAW1"))
        sfg_components = {
            "items": [{"item_code": self.SFG, "item_name": "Corn Mix", "uom": "Kg", "qty": 2.0}],
            "bom_quantity": 1000.0,
        }
        patches = [
            patch.object(mes_ops, "_require_roles"),
            patch.object(mes_ops, "_end_wo_consumption_summary", return_value={"items": []}),
            patch.object(mes_ops, "get_sfg_components_for_wo", return_value=sfg_components),
            patch.object(mes_ops, "_default_sfg_source", return_value="Semi-finished - ISN"),
            patch.object(mes_ops, "_sfg_available_qty", return_value=0.0),
            patch.object(mes_ops, "_pending_sfg_work_orders", return_value=[]),
            patch.object(mes_ops, "_is_fg", return_value=True),
            patch.object(mes_ops, "_wo_closes_at_end", return_value=False),
            patch("frappe.get_roles", return_value=[]),
            patch("frappe.get_doc", return_value=wo),
            patch("frappe.db.get_value", return_value=frappe._dict(production_item="FG10005", qty=WO_QTY)),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return mes_ops.get_end_wo_summary(WO_NAME)["sfg_items"][0]

    def test_bom_scaling_when_setting_is_off(self):
        row = self.invoke(FakeWorkOrder(wo_rows()), enabled=False)
        self.assertAlmostEqual(row["required_qty"], 2.0 * WO_QTY / 1000.0, places=4)

    def test_edited_sfg_row_drives_the_dialog(self):
        wo = FakeWorkOrder([frappe._dict(item_code=self.SFG, required_qty=0.5, stock_uom="Kg")])
        row = self.invoke(wo)
        self.assertAlmostEqual(row["required_qty"], 0.5, places=4)

    def test_untouched_sfg_falls_back_to_the_bom(self):
        """RM20003 was edited, the SFG row was not present — BOM still rules."""
        row = self.invoke(FakeWorkOrder(wo_rows()))
        self.assertAlmostEqual(row["required_qty"], 2.0 * WO_QTY / 1000.0, places=4)


class TestBomOnlyPathsUnchanged(DemandHarness):
    """Reads that must stay BOM-based are still BOM-based."""

    def test_get_bom_items_for_quantity_never_consults_the_work_order(self):
        with patch(
            "erpnext.manufacturing.doctype.bom.bom.get_bom_items_as_dict",
            return_value={RM: {"qty": BOM_REQUIRED, "stock_uom": "Kg"}},
        ):
            with patch("frappe.db.get_value", return_value="Test Co"):
                with patch.object(mes_ops.work_order_demand, "get_demand") as mock_demand:
                    out = mes_ops._get_bom_items_for_quantity(BOM_NO, WO_QTY)
        mock_demand.assert_not_called()
        self.assertEqual(out[0]["qty"], BOM_REQUIRED)

    def test_sfg_component_detection_still_reads_the_bom(self):
        bom = MagicMock()
        bom.items = [frappe._dict(item_code="SFG10001", item_name="Corn Mix", qty=2.0, uom="Kg")]
        bom.quantity = 1000.0
        with patch("frappe.db.get_value", return_value=BOM_NO):
            with patch("frappe.get_doc", return_value=bom):
                with patch.object(mes_ops, "_packaging_groups_global", return_value=set()):
                    with patch.object(mes_ops, "_backflush_groups_global", return_value=set()):
                        with patch.object(mes_ops, "_get_item_group", return_value="Semi Finished"):
                            with patch("frappe.db.exists", return_value=1):
                                out = mes_ops.get_sfg_components_for_wo(WO_NAME)
        self.assertEqual([r["item_code"] for r in out["items"]], ["SFG10001"])


class TestAcceptanceCaseMes(DemandHarness):
    """MFG-WO-2026-00026 end to end through the MES planning helper."""

    def test_downstream_planning_never_reverts_to_155_365(self):
        wo = FakeWorkOrder(wo_rows())
        self.harness(leaf=(RM,))
        with patch.object(
            mes_ops,
            "_get_bom_items_for_quantity",
            return_value=[{"item_code": RM, "qty": BOM_REQUIRED, "uom": "Kg"}],
        ):
            with patch("frappe.db.get_value", return_value="Kg"):
                planned = _planned_items_for_wo(wo, WO_QTY)

        self.assertEqual(len(planned), 1)
        self.assertAlmostEqual(planned[0]["qty"], MANUAL_REQUIRED, places=6)
        self.assertNotAlmostEqual(planned[0]["qty"], BOM_REQUIRED, places=3)


if __name__ == "__main__":
    unittest.main()
