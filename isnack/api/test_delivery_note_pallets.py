# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import patch

from isnack.api.delivery_note_pallets import (
    _apply_pallet_calculation,
    _build_pallet_suggestion,
    _pallet_conversion_factor,
    calculate_delivery_note_pallets,
    format_pallet_nos,
    get_delivery_note_pallet_conversion,
    parse_pallet_nos,
    parse_pallet_nos_for_print,
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


class TestPalletNosParsing(unittest.TestCase):
    """Tests for the Pallet No(s) range syntax ("1-3,6")."""

    def test_parse_single_and_list(self):
        self.assertEqual(parse_pallet_nos("4"), [4])
        self.assertEqual(parse_pallet_nos("4, 6"), [4, 6])

    def test_parse_range_and_mixed(self):
        self.assertEqual(parse_pallet_nos("1-3"), [1, 2, 3])
        self.assertEqual(parse_pallet_nos("1-3,6"), [1, 2, 3, 6])

    def test_parse_deduplicates_and_sorts(self):
        self.assertEqual(parse_pallet_nos("6,1-3,2"), [1, 2, 3, 6])

    def test_parse_empty_returns_empty(self):
        self.assertEqual(parse_pallet_nos(None), [])
        self.assertEqual(parse_pallet_nos("  "), [])

    def test_parse_rejects_junk(self):
        for bad in ("abc", "0", "-1", "3-1", "1,,2", "1-", "1-2-3"):
            with self.assertRaises(ValueError, msg=bad):
                parse_pallet_nos(bad)

    def test_print_variant_is_lenient(self):
        self.assertEqual(parse_pallet_nos_for_print("1-3"), [1, 2, 3])
        self.assertEqual(parse_pallet_nos_for_print("abc"), [])
        self.assertEqual(parse_pallet_nos_for_print(None), [])

    def test_format_compresses_runs(self):
        self.assertEqual(format_pallet_nos([1, 2, 3, 6]), "1-3,6")
        self.assertEqual(format_pallet_nos([4]), "4")
        self.assertEqual(format_pallet_nos([]), "")
        self.assertEqual(format_pallet_nos([2, 1, 3]), "1-3")


class TestBuildPalletSuggestion(unittest.TestCase):
    """Tests for the Build Pallets from Items suggestion."""

    @staticmethod
    def _row(name, qty, factor=100.0, pallet_type="EURO 1", **extra):
        row = {
            "name": name,
            "idx": extra.pop("idx", 1),
            "item_code": extra.pop("item_code", "FG10005"),
            "qty": qty,
            "uom": "Carton",
            "custom_pallet_type": pallet_type,
            "custom_pallet_conversion_factor": factor,
        }
        row.update(extra)
        return row

    def test_full_pallets_only(self):
        result = _build_pallet_suggestion([self._row("a", 300)])
        self.assertEqual(len(result["pallets"]), 3)
        self.assertEqual(result["assignments"], {"a": "1-3"})
        self.assertEqual(result["unassigned"], [])

    def test_remainders_share_a_mixed_pallet(self):
        # 2.4 + 0.6 pallets -> 2 full + one shared mixed pallet (no. 3).
        result = _build_pallet_suggestion(
            [self._row("a", 240), self._row("b", 60, item_code="FG10006")]
        )
        self.assertEqual(len(result["pallets"]), 3)
        self.assertEqual(result["assignments"]["a"], "1-3")
        self.assertEqual(result["assignments"]["b"], "3")

    def test_remainders_of_different_types_do_not_mix(self):
        result = _build_pallet_suggestion(
            [
                self._row("a", 40),
                self._row("b", 40, pallet_type="EURO 2", item_code="FG10006"),
            ]
        )
        self.assertEqual(len(result["pallets"]), 2)
        types = {p["pallet_no"]: p["pallet_type"] for p in result["pallets"]}
        self.assertEqual(types[1], "EURO 1")
        self.assertEqual(types[2], "EURO 2")

    def test_near_whole_fraction_snaps_to_full_pallet(self):
        result = _build_pallet_suggestion([self._row("a", 299)])
        self.assertEqual(len(result["pallets"]), 3)
        self.assertEqual(result["assignments"], {"a": "1-3"})

    def test_manual_override_wins(self):
        row = self._row(
            "a", 500, custom_pallet_qty_manual=1, custom_pallet_qty=2.0
        )
        result = _build_pallet_suggestion([row])
        self.assertEqual(len(result["pallets"]), 2)

    @patch("isnack.api.delivery_note_pallets._pallet_conversion_factor")
    def test_row_without_conversion_is_reported(self, mock_factor):
        mock_factor.return_value = None
        result = _build_pallet_suggestion([self._row("a", 100, factor=None)])
        self.assertEqual(result["pallets"], [])
        self.assertEqual(len(result["unassigned"]), 1)

    def test_rows_without_pallet_type_are_ignored(self):
        result = _build_pallet_suggestion([self._row("a", 100, pallet_type=None)])
        self.assertEqual(result["pallets"], [])
        self.assertEqual(result["unassigned"], [])


class _FakePalletDoc:
    """Delivery Note stand-in exposing items and the custom_pallets table."""

    def __init__(self, items=None, pallets=None):
        self._values = {"items": items or [], "custom_pallets": pallets or []}

    def get(self, key, default=None):
        return self._values.get(key, default)


class TestValidateDeliveryNotePallets(unittest.TestCase):
    """Tests for the pallet-table / assignment validation hook."""

    @staticmethod
    def _pallet(no, pallet_type="EURO 1", idx=1):
        return _FakeRow(pallet_no=no, pallet_type=pallet_type, idx=idx)

    def test_no_pallet_data_is_a_no_op(self):
        # Must not touch frappe at all for plain Delivery Notes.
        validate_delivery_note_pallets(_FakePalletDoc(items=[_FakeRow(idx=1)]))

    @patch("isnack.api.delivery_note_pallets.frappe.msgprint")
    def test_valid_assignment_passes(self, mock_msgprint):
        doc = _FakePalletDoc(
            items=[_FakeRow(idx=1, custom_pallet_nos="1-2", custom_pallet_type="EURO 1")],
            pallets=[self._pallet(1), self._pallet(2, idx=2)],
        )
        validate_delivery_note_pallets(doc)
        mock_msgprint.assert_not_called()

    @patch(
        "isnack.api.delivery_note_pallets.frappe.throw",
        side_effect=ValueError,
    )
    def test_duplicate_pallet_no_throws(self, _throw):
        doc = _FakePalletDoc(pallets=[self._pallet(1), self._pallet(1, idx=2)])
        with self.assertRaises(ValueError):
            validate_delivery_note_pallets(doc)

    @patch(
        "isnack.api.delivery_note_pallets.frappe.throw",
        side_effect=ValueError,
    )
    def test_reference_to_missing_pallet_throws(self, _throw):
        doc = _FakePalletDoc(
            items=[_FakeRow(idx=1, custom_pallet_nos="3")],
            pallets=[self._pallet(1)],
        )
        with self.assertRaises(ValueError):
            validate_delivery_note_pallets(doc)

    @patch(
        "isnack.api.delivery_note_pallets.frappe.throw",
        side_effect=ValueError,
    )
    def test_unparseable_assignment_throws(self, _throw):
        doc = _FakePalletDoc(
            items=[_FakeRow(idx=1, custom_pallet_nos="abc")],
            pallets=[self._pallet(1)],
        )
        with self.assertRaises(ValueError):
            validate_delivery_note_pallets(doc)

    @patch("isnack.api.delivery_note_pallets.frappe.msgprint")
    def test_unreferenced_pallet_warns(self, mock_msgprint):
        doc = _FakePalletDoc(
            items=[_FakeRow(idx=1, custom_pallet_nos="1", custom_pallet_type="EURO 1")],
            pallets=[self._pallet(1), self._pallet(2, idx=2)],
        )
        validate_delivery_note_pallets(doc)
        mock_msgprint.assert_called_once()


if __name__ == "__main__":
    unittest.main()
