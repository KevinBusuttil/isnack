# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for CustomWorkOrder — the v15.87.2 backport of ERPNext's
"Allow Editing of Items and Quantities in Work Order".

The behaviour matrix these pin, mirroring current ERPNext version-15:

    new WO, table empty            -> populate from the BOM (both settings)
    existing WO, setting OFF       -> reset required_qty from the BOM (v15.87.2)
    existing WO, setting ON        -> keep whatever the planner saved
    explicit rebuild (no reset_only_qty) -> always rebuild from the BOM

Plus the two integration facts the backport must not break: onload still carries
everything v15.87.2 put there, and registering a controller class in
``override_doctype_class`` does not displace the Work Order ``doc_events``.
"""

import os
import unittest
from unittest.mock import patch

import frappe

from isnack.overrides import work_order as work_order_override
from isnack.overrides.work_order import CustomWorkOrder


class WorkOrderStub(CustomWorkOrder):
    """Instantiates the controller without Frappe's Document machinery."""

    def __init__(self, required_items=None):
        self.required_items = required_items if required_items is not None else []
        self._onload = {}
        self.super_calls = []

    def get(self, key, default=None):
        return getattr(self, key, default)

    def set_onload(self, key, value):
        self._onload[key] = value


def wo(required_items=None):
    return WorkOrderStub(required_items=required_items)


class TestSetRequiredItems(unittest.TestCase):
    """The one method the backport overrides."""

    def _run(self, doc, reset_only_qty, enabled):
        with patch.object(work_order_override, "allow_editing_items", return_value=enabled):
            with patch(
                "erpnext.manufacturing.doctype.work_order.work_order.WorkOrder.set_required_items"
            ) as mock_super:
                doc.set_required_items(reset_only_qty=reset_only_qty)
        return mock_super

    def test_setting_off_resets_from_bom(self):
        """v15.87.2 behaviour is completely intact while the flag is off."""
        mock_super = self._run(wo([{"item_code": "RM20003"}]), reset_only_qty=1, enabled=False)
        mock_super.assert_called_once_with(reset_only_qty=1)

    def test_setting_on_skips_the_on_save_reset(self):
        mock_super = self._run(wo([{"item_code": "RM20003"}]), reset_only_qty=1, enabled=True)
        mock_super.assert_not_called()

    def test_empty_table_is_still_populated(self):
        """`validate()` passes len(required_items) — 0 here, so ERPNext fills it."""
        mock_super = self._run(wo([]), reset_only_qty=0, enabled=True)
        mock_super.assert_called_once_with(reset_only_qty=0)

    def test_empty_table_populated_even_if_reset_flag_is_truthy(self):
        """Defensive: a caller passing True on an empty table still rebuilds."""
        mock_super = self._run(wo([]), reset_only_qty=True, enabled=True)
        mock_super.assert_called_once_with(reset_only_qty=True)

    def test_explicit_bom_refresh_always_rebuilds(self):
        """get_items_and_operations_from_bom() / Production Plan pass no flag."""
        mock_super = self._run(wo([{"item_code": "RM20003"}]), reset_only_qty=False, enabled=True)
        mock_super.assert_called_once_with(reset_only_qty=False)

    def test_default_argument_rebuilds(self):
        doc = wo([{"item_code": "RM20003"}])
        with patch.object(work_order_override, "allow_editing_items", return_value=True):
            with patch(
                "erpnext.manufacturing.doctype.work_order.work_order.WorkOrder.set_required_items"
            ) as mock_super:
                doc.set_required_items()
        mock_super.assert_called_once_with(reset_only_qty=False)

    def test_returns_supers_result_when_delegating(self):
        doc = wo([])
        with patch.object(work_order_override, "allow_editing_items", return_value=True):
            with patch(
                "erpnext.manufacturing.doctype.work_order.work_order.WorkOrder.set_required_items",
                return_value="sentinel",
            ):
                self.assertEqual(doc.set_required_items(), "sentinel")

    def test_returns_none_when_suppressing(self):
        doc = wo([{"item_code": "RM20003"}])
        with patch.object(work_order_override, "allow_editing_items", return_value=True):
            self.assertIsNone(doc.set_required_items(reset_only_qty=1))


class TestOnload(unittest.TestCase):
    def _onload(self, enabled):
        doc = wo([])
        with patch.object(work_order_override, "allow_editing_items", return_value=enabled):
            with patch(
                "erpnext.manufacturing.doctype.work_order.work_order.WorkOrder.onload"
            ) as mock_super:
                doc.onload()
        return doc._onload, mock_super

    def test_extends_rather_than_replaces(self):
        _, mock_super = self._onload(True)
        mock_super.assert_called_once_with()

    def test_exposes_flag_when_enabled(self):
        onload, _ = self._onload(True)
        self.assertEqual(onload["allow_editing_items"], 1)

    def test_exposes_zero_when_disabled(self):
        onload, _ = self._onload(False)
        self.assertEqual(onload["allow_editing_items"], 0)

    def test_v15872_onload_values_survive(self):
        """The real super() must still set everything v15.87.2 set."""
        doc = wo([])
        with patch.object(work_order_override, "allow_editing_items", return_value=1):
            doc.onload()
        for key in ("material_consumption", "backflush_raw_materials_based_on", "overproduction_percentage"):
            self.assertIn(key, doc._onload)
        self.assertEqual(doc._onload["allow_editing_items"], 1)


class TestHooksRegistration(unittest.TestCase):
    """override_doctype_class and doc_events must coexist, not compete."""

    def setUp(self):
        from isnack import hooks

        self.hooks = hooks

    def test_controller_is_registered_under_the_required_name(self):
        self.assertEqual(
            self.hooks.override_doctype_class["Work Order"],
            "isnack.overrides.work_order.CustomWorkOrder",
        )

    def test_class_is_named_CustomWorkOrder(self):
        self.assertEqual(CustomWorkOrder.__name__, "CustomWorkOrder")

    def test_controller_subclasses_erpnexts_work_order(self):
        from erpnext.manufacturing.doctype.work_order.work_order import WorkOrder

        self.assertTrue(issubclass(CustomWorkOrder, WorkOrder))

    def test_existing_work_order_doc_events_are_untouched(self):
        """The Factory Section / warehouse hooks are the reason this matters."""
        self.assertEqual(
            self.hooks.doc_events["Work Order"],
            {
                "before_insert": "isnack.api.mes_ops.apply_line_warehouses_to_work_order",
                "validate": "isnack.api.mes_ops.apply_line_warehouses_to_work_order",
            },
        )

    def test_doc_events_handler_still_resolves(self):
        from isnack.api.mes_ops import apply_line_warehouses_to_work_order

        self.assertTrue(callable(apply_line_warehouses_to_work_order))

    def test_client_script_is_registered(self):
        self.assertEqual(self.hooks.doctype_js["Work Order"], "public/js/work_order.js")

    def test_custom_field_ships_as_a_module_customisation(self):
        """One persistence mechanism only — no competing fixture copy."""
        import json
        import os

        import isnack

        app_dir = os.path.dirname(os.path.abspath(isnack.__file__))
        path = os.path.join(app_dir, "isnack", "custom", "manufacturing_settings.json")
        with open(path) as f:
            data = json.load(f)

        self.assertEqual(data["doctype"], "Manufacturing Settings")
        self.assertEqual(data["sync_on_migrate"], 1)
        field = data["custom_fields"][0]
        self.assertEqual(field["fieldname"], "custom_allow_editing_of_items_and_quantities_in_work_order")
        self.assertEqual(field["label"], "Allow Editing of Items and Quantities in Work Order")
        self.assertEqual(field["fieldtype"], "Check")
        self.assertEqual(field["default"], "0")
        self.assertEqual(field["insert_after"], "column_break_lhyt")

        fixtures_path = os.path.join(app_dir, "fixtures", "custom_field.json")
        with open(fixtures_path) as f:
            fixtures = json.load(f)
        self.assertEqual(
            [f for f in fixtures if f["fieldname"] == field["fieldname"]],
            [],
            "the setting must not also be shipped as a Custom Field fixture",
        )


class TestValidateComponentsPerBomInteraction(unittest.TestCase):
    """"Validate Components and Quantities Per BOM" is a separate rule.

    ERPNext v15.87.2 StockEntry.validate() -> validate_component_and_quantities()
    compares Manufacture / Material Transfer for Manufacture rows against
    ``get_bom_raw_materials(fg_completed_qty)`` — a pure BOM read — and throws
    *Incorrect Component Quantity* or *Missing Item*. With both settings on, an
    edited Work Order therefore cannot post those entries.

    That is a deliberate business rule and this backport must never silently
    weaken it: nothing in iSnack may read, write or depend on the flag. See
    docs/work-order-item-editing.md for the full interaction.
    """

    SETTING = "validate_components_quantities_per_bom"

    def _app_sources(self):
        import os

        import isnack

        app_dir = os.path.dirname(os.path.abspath(isnack.__file__))
        for root, _dirs, files in os.walk(app_dir):
            for name in files:
                if name.endswith((".py", ".js")):
                    yield os.path.join(root, name)

    def test_isnack_never_touches_the_setting(self):
        offenders = []
        for path in self._app_sources():
            if os.path.basename(path) == os.path.basename(__file__):
                continue
            with open(path, encoding="utf-8", errors="ignore") as f:
                if self.SETTING in f.read():
                    offenders.append(path)
        self.assertEqual(
            offenders,
            [],
            "Work Order item editing must not read or change "
            f"'{self.SETTING}' — see docs/work-order-item-editing.md",
        )

    def test_backport_reads_only_its_own_setting(self):
        from isnack.utils import work_order_demand

        self.assertEqual(
            work_order_demand.ISNACK_FIELDNAME,
            "custom_allow_editing_of_items_and_quantities_in_work_order",
        )
        self.assertEqual(
            work_order_demand.UPSTREAM_FIELDNAME,
            "allow_editing_of_items_and_quantities_in_work_order",
        )
        self.assertNotIn(self.SETTING, (work_order_demand.ISNACK_FIELDNAME, work_order_demand.UPSTREAM_FIELDNAME))

    def test_interaction_is_documented(self):
        import os

        import isnack

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(isnack.__file__)))
        doc = os.path.join(repo_root, "docs", "work-order-item-editing.md")
        self.assertTrue(os.path.exists(doc), "docs/work-order-item-editing.md is missing")
        with open(doc, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Validate Components and Quantities Per BOM", text)
        self.assertIn(self.SETTING, text)


class TestAcceptanceCaseController(unittest.TestCase):
    """MFG-WO-2026-00026 / RM20003: 155.365 -> 147.910 must survive a save."""

    def test_saved_quantity_is_not_reset_when_enabled(self):
        rows = [{"item_code": "RM20003", "required_qty": 147.910}]
        doc = wo(rows)

        def erpnext_reset(reset_only_qty=False):
            # What stock v15.87.2 does: re-derive 193 * 805 / 1000.
            for row in doc.required_items:
                row["required_qty"] = 155.365

        with patch.object(work_order_override, "allow_editing_items", return_value=True):
            with patch(
                "erpnext.manufacturing.doctype.work_order.work_order.WorkOrder.set_required_items",
                side_effect=erpnext_reset,
            ):
                doc.set_required_items(reset_only_qty=len(doc.required_items))

        self.assertEqual(doc.required_items[0]["required_qty"], 147.910)

    def test_saved_quantity_is_reset_when_disabled(self):
        rows = [{"item_code": "RM20003", "required_qty": 147.910}]
        doc = wo(rows)

        def erpnext_reset(reset_only_qty=False):
            for row in doc.required_items:
                row["required_qty"] = 155.365

        with patch.object(work_order_override, "allow_editing_items", return_value=False):
            with patch(
                "erpnext.manufacturing.doctype.work_order.work_order.WorkOrder.set_required_items",
                side_effect=erpnext_reset,
            ):
                doc.set_required_items(reset_only_qty=len(doc.required_items))

        self.assertEqual(doc.required_items[0]["required_qty"], 155.365)


if __name__ == "__main__":
    unittest.main()
