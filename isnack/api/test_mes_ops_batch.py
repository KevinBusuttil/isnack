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
    """Batch rows offered by get_packaging_bom_items_for_ended_wos.

    A packaging item's batches come from three places: what the orders moved
    into WIP (directly on the ledger row, or through a Serial and Batch Bundle),
    and what was staged for them — the order's own staging transfers and the
    surplus staged for it, which reach WIP by a sweep that names no order, or
    not at all when an order was ended before Start. Each row carries what LOAD
    already consumed of that batch.
    """

    def _sql_router(self, direct=(), bundle=(), staged=(), consumed=()):
        """Answer each query by what it asks for, not by call order."""

        def side_effect(sql, params=None, as_dict=False):
            if "consumed_qty" in sql:
                return list(consumed)
            if "nullif(sed.batch_no, '')" in sql:
                return list(staged)
            if "sbe.parent = sle.serial_and_batch_bundle" in sql:
                return list(bundle)
            if "SELECT DISTINCT sle.batch_no" in sql:
                return list(direct)
            return []

        return side_effect

    def _run(self, item, mock_sql, mock_get_all, mock_warehouses_for_line,
             mock_line_for_wo, mock_packaging_groups, **sql):
        mock_packaging_groups.return_value = {"packaging"}
        mock_line_for_wo.return_value = "LINE1"
        mock_warehouses_for_line.return_value = (None, "FRY1-WIP - ISN", None, None)
        mock_get_all.side_effect = [
            [{"name": "WO-001", "bom_no": "BOM-001"}],
            [{"item_code": item["name"]}],
            [dict(item, item_group="Packaging", has_batch_no=1)],
        ]
        mock_sql.side_effect = self._sql_router(**sql)
        return get_packaging_bom_items_for_ended_wos(work_orders=json.dumps(["WO-001"]))["items"]

    CARTON = {"name": "CR30002", "item_name": "General Carton", "stock_uom": "Carton"}
    FILM = {"name": "PM40005", "item_name": "Film", "stock_uom": "Kg"}

    @patch("isnack.api.mes_ops._require_roles")
    @patch("isnack.api.mes_ops._packaging_groups_global")
    @patch("isnack.api.mes_ops._line_for_work_order")
    @patch("isnack.api.mes_ops._warehouses_for_line")
    @patch("frappe.db.get_all")
    @patch("frappe.db.sql")
    def test_batch_moved_into_wip_comes_with_what_load_consumed(self, *mocks):
        items = self._run(
            self.CARTON, *mocks[:5],
            direct=[MagicMock(batch_no="BCR30002")],
            consumed=[MagicMock(batch_no="BCR30002", consumed_qty=12.5)],
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["item_code"], "CR30002")
        self.assertEqual(items[0]["batch_no"], "BCR30002")
        self.assertEqual(items[0]["consumed_qty"], 12.5)
        self.assertEqual(items[0]["has_batch_no"], 1)

    @patch("isnack.api.mes_ops._require_roles")
    @patch("isnack.api.mes_ops._packaging_groups_global")
    @patch("isnack.api.mes_ops._line_for_work_order")
    @patch("isnack.api.mes_ops._warehouses_for_line")
    @patch("frappe.db.get_all")
    @patch("frappe.db.sql")
    def test_batch_found_via_bundle_when_direct_sle_empty(self, *mocks):
        """Batches tracked only via serial_and_batch_bundle should also be returned."""
        items = self._run(self.FILM, *mocks[:5], bundle=[MagicMock(batch_no="BPM40005")])

        self.assertEqual([(i["batch_no"], i["consumed_qty"]) for i in items], [("BPM40005", 0)])

    @patch("isnack.api.mes_ops._require_roles")
    @patch("isnack.api.mes_ops._packaging_groups_global")
    @patch("isnack.api.mes_ops._line_for_work_order")
    @patch("isnack.api.mes_ops._warehouses_for_line")
    @patch("frappe.db.get_all")
    @patch("frappe.db.sql")
    def test_no_activity_anywhere_returns_none_batch(self, *mocks):
        """Nothing moved and nothing staged: one row with no batch, still offered."""
        items = self._run(self.CARTON, *mocks[:5])

        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["batch_no"])
        self.assertIsNone(items[0]["consumed_qty"])
        self.assertEqual(items[0]["has_batch_no"], 1)

    @patch("isnack.api.mes_ops._require_roles")
    @patch("isnack.api.mes_ops._packaging_groups_global")
    @patch("isnack.api.mes_ops._line_for_work_order")
    @patch("isnack.api.mes_ops._warehouses_for_line")
    @patch("frappe.db.get_all")
    @patch("frappe.db.sql")
    def test_batch_staged_but_never_moved_into_wip_is_offered(self, *mocks):
        """MFG-WO-2026-00086: ended before Start, so nothing reached WIP and the
        dialog offered a row with no batch. The staging transfer names the
        batch."""
        items = self._run(self.CARTON, *mocks[:5], staged=[MagicMock(batch_no="jimm0709")])

        self.assertEqual([(i["batch_no"], i["consumed_qty"]) for i in items], [("jimm0709", 0)])

    @patch("isnack.api.mes_ops._require_roles")
    @patch("isnack.api.mes_ops._packaging_groups_global")
    @patch("isnack.api.mes_ops._line_for_work_order")
    @patch("isnack.api.mes_ops._warehouses_for_line")
    @patch("frappe.db.get_all")
    @patch("frappe.db.sql")
    def test_surplus_of_another_batch_gets_its_own_row(self, *mocks):
        """The sweep that moves surplus into WIP names no order, so a surplus
        batch other than the one Start moved used to have no row to enter
        against."""
        items = self._run(
            self.CARTON, *mocks[:5],
            direct=[MagicMock(batch_no="B-MAIN")],
            staged=[MagicMock(batch_no="B-MAIN"), MagicMock(batch_no="B-SURPLUS")],
        )

        self.assertEqual([i["batch_no"] for i in items], ["B-MAIN", "B-SURPLUS"])


class TestPackagingBatchesStagedFor(unittest.TestCase):
    @patch("frappe.db.sql")
    def test_reads_staging_and_surplus_transfers_for_the_orders(self, mock_sql):
        mock_sql.return_value = [MagicMock(batch_no="jimm0709"), MagicMock(batch_no=None)]

        from isnack.api.mes_ops import _packaging_batches_staged_for
        got = _packaging_batches_staged_for(["WO-86", "WO-87"], "CR30002")

        self.assertEqual(got, {"jimm0709"})
        query, params = mock_sql.call_args[0][0], mock_sql.call_args[0][1]
        self.assertEqual(params, {"item": "CR30002", "wos": ("WO-86", "WO-87")})
        self.assertIn("se.purpose = 'Material Transfer'", query)
        self.assertIn("custom_originating_work_order", query)
        self.assertIn("tabSurplus Originating Work Order", query)

    @patch("frappe.db.sql")
    def test_nothing_to_look_up_reads_nothing(self, mock_sql):
        from isnack.api.mes_ops import _packaging_batches_staged_for
        self.assertEqual(_packaging_batches_staged_for([], "CR30002"), set())
        self.assertEqual(_packaging_batches_staged_for(["WO-86"], ""), set())
        mock_sql.assert_not_called()


if __name__ == "__main__":
    unittest.main()
