# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import json
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import frappe
from isnack.api.mes_ops import (
    generate_batch_code,
    get_packaging_bom_items_for_ended_wos,
    _get_next_batch_sequence,
    _validate_batch_code_format,
)


class TestBatchCodeGeneration(unittest.TestCase):
    """Tests for ISNACK batch code generation."""
    
    def test_generate_batch_code_feb_15_2026(self):
        """Test batch code generation for February 15, 2026."""
        # February 15, 2026, sequence 1
        batch_code = generate_batch_code(date(2026, 2, 15), sequence=1)
        self.assertEqual(batch_code, "CGB-151")
    
    def test_generate_batch_code_oct_31_2026(self):
        """Test batch code generation for October 31, 2026."""
        # October 31, 2026, sequence 3
        batch_code = generate_batch_code(date(2026, 10, 31), sequence=3)
        self.assertEqual(batch_code, "CGJ-313")
    
    def test_generate_batch_code_jan_5_2027(self):
        """Test batch code generation for January 5, 2027."""
        # January 5, 2027, sequence 1
        batch_code = generate_batch_code(date(2027, 1, 5), sequence=1)
        self.assertEqual(batch_code, "CHA-051")
    
    def test_generate_batch_code_year_2025(self):
        """Test year mapping for 2025 (CF)."""
        batch_code = generate_batch_code(date(2025, 1, 1), sequence=1)
        self.assertTrue(batch_code.startswith("CF"))
    
    def test_generate_batch_code_year_2028(self):
        """Test year mapping for 2028 (CI)."""
        batch_code = generate_batch_code(date(2028, 1, 1), sequence=1)
        self.assertTrue(batch_code.startswith("CI"))
    
    def test_generate_batch_code_year_2029(self):
        """Test year mapping for 2029 (CJ)."""
        batch_code = generate_batch_code(date(2029, 1, 1), sequence=1)
        self.assertTrue(batch_code.startswith("CJ"))
    
    def test_generate_batch_code_year_2030(self):
        """Test year mapping for 2030 (DA)."""
        batch_code = generate_batch_code(date(2030, 1, 1), sequence=1)
        self.assertTrue(batch_code.startswith("DA"))
    
    def test_generate_batch_code_all_months(self):
        """Test month mapping for all 12 months."""
        month_letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']
        for month in range(1, 13):
            batch_code = generate_batch_code(date(2026, month, 15), sequence=1)
            expected_letter = month_letters[month - 1]
            self.assertEqual(batch_code[2], expected_letter, 
                           f"Month {month} should map to {expected_letter}")
    
    def test_generate_batch_code_day_padding(self):
        """Test that day is zero-padded correctly."""
        # Day 5 should be '05'
        batch_code = generate_batch_code(date(2026, 1, 5), sequence=1)
        self.assertEqual(batch_code[4:6], "05")
        
        # Day 25 should be '25'
        batch_code = generate_batch_code(date(2026, 1, 25), sequence=1)
        self.assertEqual(batch_code[4:6], "25")
    
    def test_generate_batch_code_sequence_numbers(self):
        """Test sequence number variations."""
        for seq in range(1, 10):
            batch_code = generate_batch_code(date(2026, 2, 15), sequence=seq)
            self.assertEqual(batch_code[-1], str(seq))
            self.assertEqual(len(batch_code), 7)
    
    def test_generate_batch_code_length(self):
        """Test that generated batch code is always 7 characters."""
        batch_code = generate_batch_code(date(2026, 2, 15), sequence=1)
        self.assertEqual(len(batch_code), 7)
    
    @patch('frappe.db.sql')
    def test_get_next_batch_sequence_no_existing(self, mock_sql):
        """Test sequence generation when no batches exist."""
        mock_sql.return_value = []
        sequence = _get_next_batch_sequence(date(2026, 2, 15))
        self.assertEqual(sequence, 1)
    
    @patch('frappe.db.sql')
    def test_get_next_batch_sequence_with_existing(self, mock_sql):
        """Test sequence generation with existing batches."""
        # Mock existing batch CGB-151
        mock_sql.return_value = [MagicMock(batch_id="CGB-151")]
        sequence = _get_next_batch_sequence(date(2026, 2, 15))
        self.assertEqual(sequence, 2)
    
    @patch('frappe.db.sql')
    def test_get_next_batch_sequence_multiple_existing(self, mock_sql):
        """Test sequence generation with multiple existing batches."""
        # Mock existing batch CGB-154 (highest)
        mock_sql.return_value = [MagicMock(batch_id="CGB-154")]
        sequence = _get_next_batch_sequence(date(2026, 2, 15))
        self.assertEqual(sequence, 5)
    
    @patch('frappe.db.sql')
    def test_get_next_batch_sequence_cap_at_9(self, mock_sql):
        """Test that sequence caps at 9."""
        # Mock existing batch CGB-159
        mock_sql.return_value = [MagicMock(batch_id="CGB-159")]
        sequence = _get_next_batch_sequence(date(2026, 2, 15))
        self.assertEqual(sequence, 9)


class TestBatchCodeValidation(unittest.TestCase):
    """Tests for batch code format validation."""
    
    def test_validate_valid_format(self):
        """Test validation of valid batch codes."""
        valid_codes = ["CGB-151", "CGJ-313", "CHA-051", "AAA-111", "ZZZ-999"]
        for code in valid_codes:
            try:
                result = _validate_batch_code_format(code)
                self.assertTrue(result)
            except frappe.ValidationError:
                self.fail(f"Valid code {code} raised ValidationError")
    
    @patch('frappe.throw')
    def test_validate_invalid_format_letters(self, mock_throw):
        """Test validation rejects invalid letter patterns."""
        mock_throw.side_effect = frappe.ValidationError
        
        invalid_codes = ["MGB151", "CZB151", "123456", "CGBA51", "CGB151"]
        for code in invalid_codes:
            with self.assertRaises(frappe.ValidationError):
                _validate_batch_code_format(code)
    
    @patch('frappe.throw')
    def test_validate_invalid_format_length(self, mock_throw):
        """Test validation rejects wrong length."""
        mock_throw.side_effect = frappe.ValidationError
        
        invalid_codes = ["CGB-15", "CGB-1512", "CG-151", "CGBA-151"]
        for code in invalid_codes:
            with self.assertRaises(frappe.ValidationError):
                _validate_batch_code_format(code)
    
    @patch('frappe.throw')
    def test_validate_empty_batch_no(self, mock_throw):
        """Test validation rejects empty batch number."""
        mock_throw.side_effect = frappe.ValidationError
        
        with self.assertRaises(frappe.ValidationError):
            _validate_batch_code_format("")
        
        with self.assertRaises(frappe.ValidationError):
            _validate_batch_code_format(None)
    
    @patch('frappe.throw')
    def test_validate_old_format_rejected(self, mock_throw):
        """Test validation explicitly rejects old format without dash."""
        mock_throw.side_effect = frappe.ValidationError
        
        # Old format codes (without dash) should be rejected
        old_format_codes = ["CGB151", "CGJ313", "CHA051"]
        for code in old_format_codes:
            with self.assertRaises(frappe.ValidationError):
                _validate_batch_code_format(code)
    
    def test_validate_case_insensitive(self):
        """Test validation accepts lowercase letters."""
        try:
            result = _validate_batch_code_format("cgb-151")
            self.assertTrue(result)
        except frappe.ValidationError:
            self.fail("Lowercase code raised ValidationError")


class TestGetPackagingBomItemsSLEBatchLookup(unittest.TestCase):
    """Tests for the SLE-based batch lookup in get_packaging_bom_items_for_ended_wos."""

    def _make_sql_side_effect(self, direct_batches, bundle_batches, net_qty_rows):
        """
        Return a side_effect function that returns the right mock data for each SQL call.

        Call order:
          1. Strategy-1 DISTINCT batch_no from SLE (direct)
          2. Strategy-2 DISTINCT batch_no via serial_and_batch_bundle
          3. Net qty aggregation per batch
        """
        call_count = [0]
        responses = [direct_batches, bundle_batches, net_qty_rows]

        def side_effect(sql, params=None, as_dict=False):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(responses):
                return responses[idx]
            return []

        return side_effect

    @patch("isnack.api.mes_ops._require_roles")
    @patch("isnack.api.mes_ops._packaging_groups_global")
    @patch("isnack.api.mes_ops._line_for_work_order")
    @patch("isnack.api.mes_ops._warehouses_for_line")
    @patch("frappe.db.get_all")
    @patch("frappe.db.sql")
    def test_consumed_batch_returned_with_zero_available(
        self,
        mock_sql,
        mock_get_all,
        mock_warehouses_for_line,
        mock_line_for_wo,
        mock_packaging_groups,
        mock_require_roles,
    ):
        """Batches consumed from WIP should still appear with available_qty=0."""
        mock_require_roles.return_value = None
        mock_packaging_groups.return_value = {"packaging"}
        mock_line_for_wo.return_value = "LINE1"
        mock_warehouses_for_line.return_value = (None, "FRY1-WIP - ISN", None, None)

        # frappe.db.get_all side effects: work orders, BOMs, BOM items, item data
        mock_get_all.side_effect = [
            # Work Order BOM lookup
            [{"name": "WO-001", "bom_no": "BOM-001"}],
            # BOM items
            [{"item_code": "CR30002"}],
            # Item details (has_batch_no=1, packaging group)
            [
                {
                    "name": "CR30002",
                    "item_group": "Packaging",
                    "item_name": "General Carton",
                    "stock_uom": "Carton",
                    "has_batch_no": 1,
                }
            ],
        ]

        # SQL calls: direct find → bundle find → net qty
        mock_sql.side_effect = self._make_sql_side_effect(
            direct_batches=[MagicMock(batch_no="BCR30002")],
            bundle_batches=[],
            net_qty_rows=[MagicMock(batch_no="BCR30002", net_qty=0)],
        )

        result = get_packaging_bom_items_for_ended_wos(
            work_orders=json.dumps(["WO-001"])
        )

        items = result["items"]
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["item_code"], "CR30002")
        self.assertEqual(item["batch_no"], "BCR30002")
        self.assertEqual(item["available_qty"], 0)
        self.assertEqual(item["has_batch_no"], 1)

    @patch("isnack.api.mes_ops._require_roles")
    @patch("isnack.api.mes_ops._packaging_groups_global")
    @patch("isnack.api.mes_ops._line_for_work_order")
    @patch("isnack.api.mes_ops._warehouses_for_line")
    @patch("frappe.db.get_all")
    @patch("frappe.db.sql")
    def test_batch_found_via_bundle_when_direct_sle_empty(
        self,
        mock_sql,
        mock_get_all,
        mock_warehouses_for_line,
        mock_line_for_wo,
        mock_packaging_groups,
        mock_require_roles,
    ):
        """Batches tracked only via serial_and_batch_bundle should also be returned."""
        mock_require_roles.return_value = None
        mock_packaging_groups.return_value = {"packaging"}
        mock_line_for_wo.return_value = "LINE1"
        mock_warehouses_for_line.return_value = (None, "FRY1-WIP - ISN", None, None)

        mock_get_all.side_effect = [
            [{"name": "WO-001", "bom_no": "BOM-001"}],
            [{"item_code": "PM40005"}],
            [
                {
                    "name": "PM40005",
                    "item_group": "Packaging",
                    "item_name": "Film",
                    "stock_uom": "Kg",
                    "has_batch_no": 1,
                }
            ],
        ]

        # Direct SLE has no batch; bundle lookup finds BPM40005
        mock_sql.side_effect = self._make_sql_side_effect(
            direct_batches=[],
            bundle_batches=[MagicMock(batch_no="BPM40005")],
            net_qty_rows=[MagicMock(batch_no="BPM40005", net_qty=5.0)],
        )

        result = get_packaging_bom_items_for_ended_wos(
            work_orders=json.dumps(["WO-001"])
        )

        items = result["items"]
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["item_code"], "PM40005")
        self.assertEqual(item["batch_no"], "BPM40005")
        self.assertEqual(item["available_qty"], 5.0)

    @patch("isnack.api.mes_ops._require_roles")
    @patch("isnack.api.mes_ops._packaging_groups_global")
    @patch("isnack.api.mes_ops._line_for_work_order")
    @patch("isnack.api.mes_ops._warehouses_for_line")
    @patch("frappe.db.get_all")
    @patch("frappe.db.sql")
    def test_no_sle_activity_returns_none_batch(
        self,
        mock_sql,
        mock_get_all,
        mock_warehouses_for_line,
        mock_line_for_wo,
        mock_packaging_groups,
        mock_require_roles,
    ):
        """When no SLE activity exists for a batch-tracked item, batch_no and available_qty are None."""
        mock_require_roles.return_value = None
        mock_packaging_groups.return_value = {"packaging"}
        mock_line_for_wo.return_value = "LINE1"
        mock_warehouses_for_line.return_value = (None, "FRY1-WIP - ISN", None, None)

        mock_get_all.side_effect = [
            [{"name": "WO-001", "bom_no": "BOM-001"}],
            [{"item_code": "CR30002"}],
            [
                {
                    "name": "CR30002",
                    "item_group": "Packaging",
                    "item_name": "General Carton",
                    "stock_uom": "Carton",
                    "has_batch_no": 1,
                }
            ],
        ]

        # Both SLE strategies return nothing
        mock_sql.side_effect = self._make_sql_side_effect(
            direct_batches=[],
            bundle_batches=[],
            net_qty_rows=[],
        )

        result = get_packaging_bom_items_for_ended_wos(
            work_orders=json.dumps(["WO-001"])
        )

        items = result["items"]
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["item_code"], "CR30002")
        self.assertIsNone(item["batch_no"])
        self.assertIsNone(item["available_qty"])
        self.assertEqual(item["has_batch_no"], 1)

    @patch("isnack.api.mes_ops._require_roles")
    @patch("isnack.api.mes_ops._packaging_groups_global")
    @patch("isnack.api.mes_ops._line_for_work_order")
    @patch("isnack.api.mes_ops._warehouses_for_line")
    @patch("frappe.db.get_all")
    @patch("frappe.db.sql")
    def test_positive_available_qty_returned_correctly(
        self,
        mock_sql,
        mock_get_all,
        mock_warehouses_for_line,
        mock_line_for_wo,
        mock_packaging_groups,
        mock_require_roles,
    ):
        """Batches with positive net qty are returned with the correct available_qty."""
        mock_require_roles.return_value = None
        mock_packaging_groups.return_value = {"packaging"}
        mock_line_for_wo.return_value = "LINE1"
        mock_warehouses_for_line.return_value = (None, "FRY1-WIP - ISN", None, None)

        mock_get_all.side_effect = [
            [{"name": "WO-001", "bom_no": "BOM-001"}],
            [{"item_code": "CR30002"}],
            [
                {
                    "name": "CR30002",
                    "item_group": "Packaging",
                    "item_name": "General Carton",
                    "stock_uom": "Carton",
                    "has_batch_no": 1,
                }
            ],
        ]

        mock_sql.side_effect = self._make_sql_side_effect(
            direct_batches=[MagicMock(batch_no="BCR30002")],
            bundle_batches=[],
            net_qty_rows=[MagicMock(batch_no="BCR30002", net_qty=12.5)],
        )

        result = get_packaging_bom_items_for_ended_wos(
            work_orders=json.dumps(["WO-001"])
        )

        items = result["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["batch_no"], "BCR30002")
        self.assertEqual(items[0]["available_qty"], 12.5)


if __name__ == "__main__":
    unittest.main()
