# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Storekeeper Hub demand when Work Order quantities are editable.

The Hub derives what a Work Order needs from the BOM. Once a planner is allowed
to hand-edit ``Work Order.required_items`` that is no longer the whole truth:
MFG-WO-2026-00026 cut RM20003 from 155.365 kg (193 x 805 / 1000) to 147.910 kg,
and staging 147.910 must read as *Staged*, not *Partial*.

What must NOT change is membership. Consolidated staging deliberately works
against the DIRECT leaf BOM rows so a parent finished-good Work Order never
claims raw materials belonging to a separate semi-finished Work Order. These
tests pin both halves: the quantity follows the Work Order, the membership
follows the BOM.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from isnack.isnack.page.storekeeper_hub import storekeeper_hub
from isnack.isnack.page.storekeeper_hub.storekeeper_hub import (
    _remaining_leaf_map_for_wo,
    _required_leaf_map_for_wo,
    _required_map_for_wo,
    _stage_status,
    create_consolidated_transfers,
)

WO_NAME = "MFG-WO-2026-00026"
BOM_NO = "BOM-FG10005-001"
WO_QTY = 193.0
RM = "RM20003"
BOM_PER_UNIT = 0.805  # 805 kg per 1000 units
BOM_REQUIRED = 155.365
MANUAL_REQUIRED = 147.910


class FakeWorkOrder:
    def __init__(self, required_items=None, use_multi_level_bom=0, name=WO_NAME):
        self.name = name
        self.bom_no = BOM_NO
        self.qty = WO_QTY
        self.company = "Test Co"
        self.wip_warehouse = "WIP - ISN"
        self.use_multi_level_bom = use_multi_level_bom
        self.required_items = required_items if required_items is not None else []
        self.planned_start_date = "2026-01-01"

    def get(self, key, default=None):
        return getattr(self, key, default)


def wo_rows(rm_qty=MANUAL_REQUIRED, extra=()):
    rows = [frappe._dict(item_code=RM, required_qty=rm_qty, stock_uom="Kg")]
    rows.extend(frappe._dict(**r) for r in extra)
    return rows


def bom_leaf_rows(items=((RM, BOM_PER_UNIT),)):
    return [frappe._dict(item_code=code, stock_uom="Kg", qty_per_unit=per_unit) for code, per_unit in items]


def explosion_rows(items=((RM, BOM_PER_UNIT),)):
    return [frappe._dict(item_code=code, stock_uom="Kg", qty_per_unit=per_unit) for code, per_unit in items]


class DemandHarness(unittest.TestCase):
    """Patches the BOM reads both the Hub and the overlay perform.

    ``leaf`` are the WO BOM's direct rows without their own BOM, ``sub`` its
    direct sub-assembly rows, ``exploded`` the whole tree's leaves.
    """

    def harness(
        self,
        work_order,
        enabled=True,
        leaf=(RM,),
        sub=(),
        exploded=None,
        leaf_rows=None,
        explosion=None,
        transferred=None,
    ):
        exploded = list(exploded) if exploded is not None else list(leaf)
        leaf_rows = leaf_rows if leaf_rows is not None else bom_leaf_rows()
        explosion = explosion if explosion is not None else explosion_rows()

        def fake_sql(query, values=None, as_dict=False, **kwargs):
            if "tabBOM Explosion Item" in query:
                return explosion
            if "tabBOM Item" in query:
                return leaf_rows
            return []

        def fake_get_all(doctype, filters=None, fields=None, **kwargs):
            if doctype == "BOM Item":
                return [{"item_code": c} for c in list(leaf) + list(sub)]
            if doctype == "BOM Explosion Item":
                return [{"item_code": c} for c in exploded]
            return []

        def fake_bom_items_as_dict(bom_no, company, qty=1, fetch_exploded=0, **kwargs):
            codes = exploded if fetch_exploded else list(leaf) + list(sub)
            return {c: {"qty": 1.0} for c in codes}

        def fake_get_value(doctype, name, fieldname=None, *args, **kwargs):
            if doctype == "Item":
                return "Kg"
            return "Test Co"

        patches = [
            patch.object(storekeeper_hub.work_order_demand, "allow_editing_items", return_value=enabled),
            patch("frappe.get_doc", return_value=work_order),
            patch("frappe.db.sql", side_effect=fake_sql),
            patch("frappe.get_all", side_effect=fake_get_all),
            patch("frappe.db.get_value", side_effect=fake_get_value),
            patch(
                "erpnext.manufacturing.doctype.bom.bom.get_bom_items_as_dict",
                side_effect=fake_bom_items_as_dict,
            ),
            patch.object(storekeeper_hub, "_staging_for", return_value="Staging - ISN"),
            patch.object(
                storekeeper_hub, "_transferred_map_for_wo", return_value=dict(transferred or {})
            ),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])


class TestRequiredLeafMap(DemandHarness):
    def test_setting_off_keeps_the_bom_quantity(self):
        """Strong regression check: default OFF must be byte-identical to today."""
        self.harness(FakeWorkOrder(wo_rows()), enabled=False)
        self.assertAlmostEqual(_required_leaf_map_for_wo(WO_NAME)[RM]["qty"], BOM_REQUIRED, places=6)

    def test_manual_quantity_becomes_the_requirement(self):
        self.harness(FakeWorkOrder(wo_rows()))
        self.assertAlmostEqual(_required_leaf_map_for_wo(WO_NAME)[RM]["qty"], MANUAL_REQUIRED, places=6)

    def test_uom_is_preserved(self):
        self.harness(FakeWorkOrder(wo_rows()))
        self.assertEqual(_required_leaf_map_for_wo(WO_NAME)[RM]["uom"], "Kg")

    def test_empty_required_items_falls_back_to_the_bom(self):
        self.harness(FakeWorkOrder([]))
        self.assertAlmostEqual(_required_leaf_map_for_wo(WO_NAME)[RM]["qty"], BOM_REQUIRED, places=6)

    def test_deleted_row_removes_the_requirement(self):
        self.harness(FakeWorkOrder(wo_rows(extra=[{"item_code": "RM20004", "required_qty": 4.0}])[1:]))
        self.assertNotIn(RM, _required_leaf_map_for_wo(WO_NAME))

    def test_manual_item_joins_the_requirement(self):
        rows = wo_rows(extra=[{"item_code": "RM99999", "required_qty": 5.0}])
        self.harness(FakeWorkOrder(rows))
        out = _required_leaf_map_for_wo(WO_NAME)
        self.assertEqual(out["RM99999"]["qty"], 5.0)
        self.assertEqual(out["RM99999"]["uom"], "Kg")

    def test_exploded_map_also_follows_the_work_order(self):
        self.harness(FakeWorkOrder(wo_rows()))
        self.assertAlmostEqual(_required_map_for_wo(WO_NAME)[RM]["qty"], MANUAL_REQUIRED, places=6)


class TestSubAssemblySeparation(DemandHarness):
    """A parent FG Work Order must not start staging its SFG's raw materials."""

    def parent_wo(self, extra=()):
        return FakeWorkOrder(wo_rows(extra=extra))

    def harness_parent(self, wo, enabled=True):
        # Direct rows: RM20003 (leaf) + SFG10001 (sub-assembly).
        # Exploded rows additionally carry SFGRAW1, which belongs to the SFG's
        # own Work Order and is staged there, never here.
        self.harness(
            wo,
            enabled=enabled,
            leaf=(RM,),
            sub=("SFG10001",),
            exploded=(RM, "SFGRAW1"),
            leaf_rows=bom_leaf_rows(((RM, BOM_PER_UNIT),)),
            explosion=explosion_rows(((RM, BOM_PER_UNIT), ("SFGRAW1", 0.1))),
        )

    def test_leaf_map_excludes_the_sub_assembly_and_its_raws(self):
        self.harness_parent(self.parent_wo())
        out = _required_leaf_map_for_wo(WO_NAME)
        self.assertEqual(set(out), {RM})

    def test_sfg_raw_material_on_the_work_order_is_not_promoted(self):
        """Even if an SFG raw material appears on the parent's table, the
        direct-leaf rule wins: it is BOM-known, so it is never 'manual'."""
        self.harness_parent(self.parent_wo(extra=[{"item_code": "SFGRAW1", "required_qty": 19.3}]))
        out = _required_leaf_map_for_wo(WO_NAME)
        self.assertNotIn("SFGRAW1", out)

    def test_exploded_map_keeps_out_of_scope_rows_at_bom_quantity(self):
        """SFGRAW1 is outside a single-level WO's table, so the BOM still rules."""
        self.harness_parent(self.parent_wo())
        out = _required_map_for_wo(WO_NAME)
        self.assertAlmostEqual(out["SFGRAW1"]["qty"], 0.1 * WO_QTY, places=6)
        self.assertAlmostEqual(out[RM]["qty"], MANUAL_REQUIRED, places=6)

    def test_unchanged_when_setting_is_off(self):
        self.harness_parent(self.parent_wo(), enabled=False)
        self.assertEqual(set(_required_leaf_map_for_wo(WO_NAME)), {RM})
        self.assertAlmostEqual(_required_leaf_map_for_wo(WO_NAME)[RM]["qty"], BOM_REQUIRED, places=6)


class TestRemainingAndStatus(DemandHarness):
    def test_remaining_is_measured_against_the_manual_requirement(self):
        self.harness(FakeWorkOrder(wo_rows()), transferred={RM: 100.0})
        self.assertAlmostEqual(_remaining_leaf_map_for_wo(WO_NAME)[RM]["qty"], 47.910, places=6)

    def test_manual_requirement_fully_staged_leaves_nothing_remaining(self):
        self.harness(FakeWorkOrder(wo_rows()), transferred={RM: MANUAL_REQUIRED})
        self.assertNotIn(RM, _remaining_leaf_map_for_wo(WO_NAME))

    def test_setting_off_still_wants_the_bom_shortfall(self):
        self.harness(FakeWorkOrder(wo_rows()), enabled=False, transferred={RM: MANUAL_REQUIRED})
        self.assertAlmostEqual(
            _remaining_leaf_map_for_wo(WO_NAME)[RM]["qty"], BOM_REQUIRED - MANUAL_REQUIRED, places=6
        )


class TestStageStatus(unittest.TestCase):
    """`_stage_status` reads transfers itself, so it gets its own harness."""

    def harness(self, work_order, staged_qty, enabled=True, leaf=(RM,), exploded=None):
        exploded = list(exploded) if exploded is not None else list(leaf)

        def fake_sql(query, values=None, as_dict=False, **kwargs):
            if "tabBOM Explosion Item" in query:
                return explosion_rows()
            if "tabBOM Item" in query:
                return bom_leaf_rows()
            if "tabStock Entry" in query:
                return [frappe._dict(item_code=RM, qty=staged_qty)] if staged_qty is not None else []
            return []

        def fake_get_all(doctype, filters=None, fields=None, **kwargs):
            if doctype == "BOM Item":
                return [{"item_code": c} for c in leaf]
            if doctype == "BOM Explosion Item":
                return [{"item_code": c} for c in exploded]
            return []

        patches = [
            patch.object(storekeeper_hub.work_order_demand, "allow_editing_items", return_value=enabled),
            patch("frappe.get_doc", return_value=work_order),
            patch("frappe.db.sql", side_effect=fake_sql),
            patch("frappe.get_all", side_effect=fake_get_all),
            patch("frappe.db.get_value", return_value="Test Co"),
            patch("frappe.get_precision", return_value=3),
            patch(
                "erpnext.manufacturing.doctype.bom.bom.get_bom_items_as_dict",
                side_effect=lambda *a, **k: {c: {"qty": 1.0} for c in leaf},
            ),
            patch.object(storekeeper_hub, "_staging_for", return_value="Staging - ISN"),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

    def test_manual_requirement_staged_in_full_reads_as_staged(self):
        """The acceptance case: 147.910 staged must not read 'Partial'."""
        self.harness(FakeWorkOrder(wo_rows()), staged_qty=MANUAL_REQUIRED)
        self.assertEqual(_stage_status(WO_NAME), "Staged")

    def test_same_quantity_is_partial_while_the_setting_is_off(self):
        self.harness(FakeWorkOrder(wo_rows()), staged_qty=MANUAL_REQUIRED, enabled=False)
        self.assertEqual(_stage_status(WO_NAME), "Partial")

    def test_short_of_the_manual_requirement_is_partial(self):
        self.harness(FakeWorkOrder(wo_rows()), staged_qty=100.0)
        self.assertEqual(_stage_status(WO_NAME), "Partial")

    def test_nothing_transferred_is_not_staged(self):
        self.harness(FakeWorkOrder(wo_rows()), staged_qty=None)
        self.assertEqual(_stage_status(WO_NAME), "Not Staged")


class TestConsolidatedAllocation(unittest.TestCase):
    """Allocation is capped by remaining demand, so the cap must follow the WO."""

    def run_allocation(self, cart_qty, enabled=True, required_qty=MANUAL_REQUIRED):
        work_order = FakeWorkOrder(wo_rows(rm_qty=required_qty))
        created = []

        def fake_new_doc(doctype):
            se = MagicMock()
            se.items = []
            se.origin_rows = []

            def append(table, row):
                # A surplus entry also fills custom_originating_work_orders;
                # keep the two tables apart or the item assertions read a
                # provenance row.
                (se.items if table == "items" else se.origin_rows).append(row)

            se.append = append
            se.get = lambda table, default=None: se.items if table == "items" else default
            se.name = f"MAT-STE-{len(created) + 1:05d}"
            se.insert = MagicMock()
            se.submit = MagicMock()
            created.append(se)
            return se

        def fake_get_all(doctype, filters=None, fields=None, **kwargs):
            if doctype == "Item":
                return [frappe._dict(name=RM, has_batch_no=0)]
            if doctype == "Work Order":
                return [frappe._dict(name=WO_NAME)]
            if doctype == "BOM Item":
                return [{"item_code": RM}]
            if doctype == "BOM Explosion Item":
                return [{"item_code": RM}]
            return []

        def fake_sql(query, values=None, as_dict=False, **kwargs):
            if "tabBOM Item" in query:
                return bom_leaf_rows()
            if "tabBOM Explosion Item" in query:
                return explosion_rows()
            return []

        patches = [
            patch.object(storekeeper_hub.work_order_demand, "allow_editing_items", return_value=enabled),
            patch("frappe.get_doc", return_value=work_order),
            patch("frappe.get_all", side_effect=fake_get_all),
            patch("frappe.db.sql", side_effect=fake_sql),
            patch("frappe.db.get_value", return_value="Kg"),
            patch("frappe.new_doc", side_effect=fake_new_doc),
            patch(
                "erpnext.manufacturing.doctype.bom.bom.get_bom_items_as_dict",
                side_effect=lambda *a, **k: {RM: {"qty": 1.0}},
            ),
            patch.object(storekeeper_hub, "_staging_for", return_value="Staging - ISN"),
            patch.object(storekeeper_hub, "_transferred_map_for_wo", return_value={}),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        result = create_consolidated_transfers(
            pallet_id="",
            source_warehouse="Stores - ISN",
            selected_wos=[WO_NAME],
            items=[{"item_code": RM, "qty": cart_qty}],
        )
        return result, created

    def test_allocation_is_capped_at_the_manual_requirement(self):
        """Picking the full BOM quantity must only allocate 147.910 to the WO;
        the rest becomes surplus, exactly as an over-pick always did."""
        result, created = self.run_allocation(BOM_REQUIRED)

        wo_entries = [se for se in created if se.work_order == WO_NAME]
        self.assertEqual(len(wo_entries), 1)
        self.assertAlmostEqual(wo_entries[0].items[0]["qty"], MANUAL_REQUIRED, places=3)

        surplus = [se for se in created if se.custom_is_surplus == 1]
        self.assertEqual(len(surplus), 1)
        # The remainder is placed in staging as surplus, rounded up at the
        # posting precision exactly as any other over-pick is.
        self.assertEqual(
            surplus[0].items[0]["qty"],
            storekeeper_hub._round_up_qty(BOM_REQUIRED - MANUAL_REQUIRED, 3),
        )

    def test_exact_manual_quantity_creates_no_surplus(self):
        result, created = self.run_allocation(MANUAL_REQUIRED)
        self.assertEqual(len(created), 1)
        self.assertAlmostEqual(created[0].items[0]["qty"], MANUAL_REQUIRED, places=3)
        self.assertFalse(any(t.get("is_surplus") for t in result["transfers"]))

    def test_setting_off_allocates_the_full_bom_quantity(self):
        _, created = self.run_allocation(BOM_REQUIRED, enabled=False)
        self.assertEqual(len(created), 1)
        self.assertAlmostEqual(created[0].items[0]["qty"], BOM_REQUIRED, places=3)


if __name__ == "__main__":
    unittest.main()
