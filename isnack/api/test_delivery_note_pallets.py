# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import patch

from isnack.api.delivery_note_pallets import (
    _apply_pallet_calculation,
    _build_pallet_suggestion,
    _pallet_conversion_factor,
    calculate_delivery_note_pallets,
    get_bundle_batches,
    get_delivery_note_pallet_conversion,
    validate_delivery_note_pallets,
)


class _FakeRow:
    """Minimal stand-in for a Delivery Note Item child document."""

    def __init__(self, **values):
        self.__dict__.update(values)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


class _FakeDoc:
    def __init__(self, items):
        self._items = items

    def get(self, key, default=None):
        return self._items if key == "items" else default


class TestDeliveryNotePalletConversion(unittest.TestCase):
    """Tests for the Delivery Note specific pallet conversion logic."""

    def test_same_uom_returns_one(self):
        self.assertEqual(
            _pallet_conversion_factor("FG10005", "Carton", "Carton"), 1.0
        )

    def test_missing_parameters_returns_none(self):
        self.assertIsNone(_pallet_conversion_factor("", "Carton", "EURO 1"))
        self.assertIsNone(_pallet_conversion_factor("FG10005", "", "EURO 1"))
        self.assertIsNone(_pallet_conversion_factor("FG10005", "Carton", ""))

    @patch("isnack.api.delivery_note_pallets.frappe.get_cached_value")
    @patch("isnack.api.delivery_note_pallets.frappe.db.get_value")
    def test_item_uom_conversion_from_stock_uom(self, mock_get_value, mock_cached):
        # Stock UOM is Carton, so from_uom needs no lookup; 1 pallet = 100 Cartons.
        mock_cached.return_value = "Carton"
        mock_get_value.return_value = 100.0

        factor = _pallet_conversion_factor("FG10005", "Carton", "EURO 1")

        self.assertEqual(factor, 100.0)

    @patch("isnack.api.delivery_note_pallets.frappe.get_cached_value")
    @patch("isnack.api.delivery_note_pallets.frappe.db.get_value")
    def test_global_uom_conversion(self, mock_get_value, mock_cached):
        # No stock UOM -> item lookup skipped; direct global conversion used.
        mock_cached.return_value = None
        mock_get_value.return_value = 50.0

        factor = _pallet_conversion_factor("FG10005", "Box", "EURO 1")

        self.assertEqual(factor, 50.0)

    @patch("isnack.api.delivery_note_pallets.frappe.get_cached_value")
    @patch("isnack.api.delivery_note_pallets.frappe.db.get_value")
    def test_inverse_global_uom_conversion(self, mock_get_value, mock_cached):
        mock_cached.return_value = None
        # Direct global conversion missing, inverse (pallet -> box) = 4.
        mock_get_value.side_effect = [None, 4.0]

        factor = _pallet_conversion_factor("FG10005", "Box", "EURO 1")

        self.assertAlmostEqual(factor, 0.25, places=6)

    @patch("isnack.api.delivery_note_pallets.frappe.get_cached_value")
    @patch("isnack.api.delivery_note_pallets.frappe.db.get_value")
    def test_no_conversion_found(self, mock_get_value, mock_cached):
        mock_cached.return_value = None
        mock_get_value.return_value = None

        self.assertIsNone(_pallet_conversion_factor("FG10005", "Box", "EURO 1"))


class TestApplyPalletCalculation(unittest.TestCase):
    """Tests for the per-row Delivery Note Item pallet calculation."""

    @patch("isnack.api.delivery_note_pallets._pallet_conversion_factor")
    def test_fg10005_example(self, mock_factor):
        # FG10005: 2000 Cartons, 1 pallet UOM = 100 Cartons -> 20 pallets.
        mock_factor.return_value = 100.0
        row = _FakeRow(
            item_code="FG10005",
            qty=2000,
            uom="Carton",
            custom_pallet_type="EURO 1",
        )

        _apply_pallet_calculation(row)

        self.assertEqual(row.custom_pallet_qty, 20.0)
        self.assertEqual(row.custom_pallet_conversion_factor, 100.0)

    @patch("isnack.api.delivery_note_pallets._pallet_conversion_factor")
    def test_manual_override_is_preserved(self, mock_factor):
        row = _FakeRow(
            item_code="FG10005",
            qty=2000,
            uom="Carton",
            custom_pallet_type="EURO 1",
            custom_pallet_qty=7,
            custom_pallet_qty_manual=1,
        )

        _apply_pallet_calculation(row)

        # The manual value is untouched and no conversion lookup happens.
        self.assertEqual(row.custom_pallet_qty, 7)
        mock_factor.assert_not_called()

    @patch("isnack.api.delivery_note_pallets._pallet_conversion_factor")
    def test_no_conversion_leaves_pallet_qty_blank(self, mock_factor):
        mock_factor.return_value = None
        row = _FakeRow(
            item_code="FG10005",
            qty=2000,
            uom="Carton",
            custom_pallet_type="EURO 1",
        )

        _apply_pallet_calculation(row)

        self.assertIsNone(row.custom_pallet_qty)
        self.assertIsNone(row.custom_pallet_conversion_factor)

    @patch("isnack.api.delivery_note_pallets._pallet_conversion_factor")
    def test_missing_pallet_type_clears_fields(self, mock_factor):
        row = _FakeRow(item_code="FG10005", qty=2000, uom="Carton")

        _apply_pallet_calculation(row)

        self.assertIsNone(row.custom_pallet_qty)
        self.assertIsNone(row.custom_pallet_conversion_factor)
        mock_factor.assert_not_called()

    @patch("isnack.api.delivery_note_pallets._pallet_conversion_factor")
    def test_validate_hook_processes_every_row(self, mock_factor):
        mock_factor.return_value = 100.0
        doc = _FakeDoc(
            [
                _FakeRow(
                    item_code="FG10005",
                    qty=2000,
                    uom="Carton",
                    custom_pallet_type="EURO 1",
                ),
                _FakeRow(
                    item_code="FG10006",
                    qty=500,
                    uom="Carton",
                    custom_pallet_type="EURO 1",
                ),
            ]
        )

        calculate_delivery_note_pallets(doc)

        self.assertEqual(doc._items[0].custom_pallet_qty, 20.0)
        self.assertEqual(doc._items[1].custom_pallet_qty, 5.0)


class TestGetDeliveryNotePalletConversion(unittest.TestCase):
    """Tests for the whitelisted client-facing conversion endpoint."""

    @patch("isnack.api.delivery_note_pallets._pallet_conversion_factor")
    def test_found(self, mock_factor):
        mock_factor.return_value = 100.0
        result = get_delivery_note_pallet_conversion("FG10005", "Carton", "EURO 1")
        self.assertTrue(result["found"])
        self.assertEqual(result["conversion_factor"], 100.0)

    @patch("isnack.api.delivery_note_pallets._pallet_conversion_factor")
    def test_not_found(self, mock_factor):
        mock_factor.return_value = None
        result = get_delivery_note_pallet_conversion("FG10005", "Carton", "EURO 1")
        self.assertFalse(result["found"])
        self.assertIsNone(result["conversion_factor"])


class TestBuildPalletSuggestion(unittest.TestCase):
    """Tests for the Build Pallets from Items manifest suggestion."""

    @staticmethod
    def _row(name, qty, factor=100.0, pallet_type="EURO 1", **extra):
        row = {
            "name": name,
            "idx": extra.pop("idx", 1),
            "item_code": extra.pop("item_code", "FG10005"),
            "batch_no": extra.pop("batch_no", None),
            "qty": qty,
            "uom": "Carton",
            "custom_pallet_type": pallet_type,
            "custom_pallet_conversion_factor": factor,
        }
        row.update(extra)
        return row

    def test_full_pallets_get_exact_quantities(self):
        result = _build_pallet_suggestion([self._row("a", 300)])
        allocations = result["allocations"]
        self.assertEqual(len(allocations), 3)
        self.assertEqual([a["pallet_no"] for a in allocations], [1, 2, 3])
        self.assertEqual([a["qty"] for a in allocations], [100.0, 100.0, 100.0])
        self.assertEqual(result["unassigned"], [])

    def test_remainders_share_a_mixed_pallet_with_exact_quantities(self):
        # 240 + 60 cartons at 100/pallet -> pallets 1-2 full of item A,
        # pallet 3 mixed holding 40 of A and 60 of B.
        result = _build_pallet_suggestion(
            [
                self._row("a", 240, batch_no="B-105"),
                self._row("b", 60, item_code="FG10006", batch_no="B-207"),
            ]
        )
        allocations = result["allocations"]
        by_pallet = {}
        for a in allocations:
            by_pallet.setdefault(a["pallet_no"], []).append(a)
        self.assertEqual(sorted(by_pallet), [1, 2, 3])
        self.assertEqual([a["qty"] for a in by_pallet[1]], [100.0])
        self.assertEqual([a["qty"] for a in by_pallet[2]], [100.0])
        mixed = sorted((a["item_code"], a["qty"]) for a in by_pallet[3])
        self.assertEqual(mixed, [("FG10005", 40.0), ("FG10006", 60.0)])
        self.assertEqual(by_pallet[3][0]["batch_no"], "B-105")

    def test_remainders_of_different_types_do_not_mix(self):
        result = _build_pallet_suggestion(
            [
                self._row("a", 6, factor=77, pallet_type="EUR 1 Pallet x 77"),
                self._row(
                    "b",
                    4,
                    factor=66,
                    pallet_type="EUR 1 Pallet x 66",
                    item_code="FG10010",
                ),
            ]
        )
        allocations = result["allocations"]
        self.assertEqual(len(allocations), 2)
        self.assertEqual(
            [(a["pallet_no"], a["pallet_type"], a["qty"]) for a in allocations],
            [(1, "EUR 1 Pallet x 77", 6.0), (2, "EUR 1 Pallet x 66", 4.0)],
        )

    def test_near_whole_fraction_snaps_to_full_pallets(self):
        result = _build_pallet_suggestion([self._row("a", 299)])
        allocations = result["allocations"]
        self.assertEqual(len(allocations), 3)
        self.assertAlmostEqual(sum(a["qty"] for a in allocations), 299.0, places=2)

    def test_manual_override_splits_evenly(self):
        row = self._row(
            "a", 500, custom_pallet_qty_manual=1, custom_pallet_qty=2.0
        )
        result = _build_pallet_suggestion([row])
        allocations = result["allocations"]
        self.assertEqual([a["qty"] for a in allocations], [250.0, 250.0])

    @patch("isnack.api.delivery_note_pallets._pallet_conversion_factor")
    def test_row_without_conversion_is_reported(self, mock_factor):
        mock_factor.return_value = None
        result = _build_pallet_suggestion([self._row("a", 100, factor=None)])
        self.assertEqual(result["allocations"], [])
        self.assertEqual(len(result["unassigned"]), 1)

    def test_rows_without_pallet_type_are_ignored(self):
        result = _build_pallet_suggestion([self._row("a", 100, pallet_type=None)])
        self.assertEqual(result["allocations"], [])
        self.assertEqual(result["unassigned"], [])


class _FakePalletDoc:
    """Delivery Note stand-in exposing items and the custom_pallets manifest."""

    def __init__(self, items=None, pallets=None):
        self._values = {"items": items or [], "custom_pallets": pallets or []}

    def get(self, key, default=None):
        return self._values.get(key, default)


class TestValidateDeliveryNotePallets(unittest.TestCase):
    """Tests for the pallet-manifest validation hook."""

    @staticmethod
    def _allocation(no, item="FG10005", qty=10.0, pallet_type="EURO 1", **extra):
        values = {
            "pallet_no": no,
            "pallet_type": pallet_type,
            "item_code": item,
            "batch_no": extra.pop("batch_no", None),
            "qty": qty,
            "idx": extra.pop("idx", 1),
        }
        values.update(extra)
        return _FakeRow(**values)

    @staticmethod
    def _item(item="FG10005", qty=10.0, batch_no=None, idx=1):
        return _FakeRow(item_code=item, qty=qty, batch_no=batch_no, idx=idx)

    def test_no_manifest_is_a_no_op(self):
        validate_delivery_note_pallets(_FakePalletDoc(items=[self._item()]))

    @patch("isnack.api.delivery_note_pallets.frappe.msgprint")
    def test_matching_manifest_passes_silently(self, mock_msgprint):
        doc = _FakePalletDoc(
            items=[self._item(qty=10)],
            pallets=[
                self._allocation(1, qty=6),
                self._allocation(2, qty=4, idx=2),
            ],
        )
        validate_delivery_note_pallets(doc)
        mock_msgprint.assert_not_called()

    @patch(
        "isnack.api.delivery_note_pallets.frappe.throw",
        side_effect=ValueError,
    )
    def test_conflicting_types_on_one_pallet_throw(self, _throw):
        doc = _FakePalletDoc(
            pallets=[
                self._allocation(1, pallet_type="EURO 1"),
                self._allocation(1, pallet_type="EURO 2", idx=2),
            ]
        )
        with self.assertRaises(ValueError):
            validate_delivery_note_pallets(doc)

    @patch(
        "isnack.api.delivery_note_pallets.frappe.throw",
        side_effect=ValueError,
    )
    def test_structural_problems_throw(self, _throw):
        for pallets in (
            [self._allocation(0)],
            [self._allocation(1, pallet_type=None)],
            [self._allocation(1, item=None)],
            [self._allocation(1, qty=0)],
        ):
            with self.assertRaises(ValueError):
                validate_delivery_note_pallets(_FakePalletDoc(pallets=pallets))

    @patch("isnack.api.delivery_note_pallets.frappe.msgprint")
    def test_quantity_mismatch_warns(self, mock_msgprint):
        doc = _FakePalletDoc(
            items=[self._item(qty=10)],
            pallets=[self._allocation(1, qty=7)],
        )
        validate_delivery_note_pallets(doc)
        mock_msgprint.assert_called_once()

    @patch("isnack.api.delivery_note_pallets.frappe.msgprint")
    def test_item_not_on_delivery_note_warns(self, mock_msgprint):
        doc = _FakePalletDoc(
            items=[self._item(item="FG10005", qty=10)],
            pallets=[self._allocation(1, item="FG10099", qty=10)],
        )
        validate_delivery_note_pallets(doc)
        mock_msgprint.assert_called_once()


class TestGetBundleBatches(unittest.TestCase):
    """Tests for the Serial and Batch Bundle -> batch numbers helper."""

    def test_empty_input_returns_empty(self):
        self.assertEqual(get_bundle_batches([]), {})
        self.assertEqual(get_bundle_batches(None), {})

    @patch("isnack.api.delivery_note_pallets.frappe.get_all")
    def test_batches_grouped_and_deduplicated_per_bundle(self, mock_get_all):
        mock_get_all.return_value = [
            _FakeRow(parent="SABB-001", batch_no="AAA-005"),
            _FakeRow(parent="SABB-001", batch_no="ZZZ-005"),
            _FakeRow(parent="SABB-001", batch_no="AAA-005"),
            _FakeRow(parent="SABB-002", batch_no="BBB-001"),
        ]
        result = get_bundle_batches(["SABB-001", "SABB-002"])
        self.assertEqual(result["SABB-001"], ["AAA-005", "ZZZ-005"])
        self.assertEqual(result["SABB-002"], ["BBB-001"])
        kwargs = mock_get_all.call_args.kwargs
        self.assertEqual(kwargs.get("parent_doctype"), "Serial and Batch Bundle")


if __name__ == "__main__":
    unittest.main()
