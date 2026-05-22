# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import patch

from isnack.api.delivery_note_pallets import (
    _apply_pallet_calculation,
    _pallet_conversion_factor,
    calculate_delivery_note_pallets,
    get_delivery_note_pallet_conversion,
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


if __name__ == "__main__":
    unittest.main()
