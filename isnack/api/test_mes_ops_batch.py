# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import frappe
from isnack.api.mes_ops import (
    generate_batch_code,
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
    
    def test_validate_case_insensitive(self):
        """Test validation accepts lowercase letters."""
        try:
            result = _validate_batch_code_format("cgb-151")
            self.assertTrue(result)
        except frappe.ValidationError:
            self.fail("Lowercase code raised ValidationError")


if __name__ == "__main__":
    unittest.main()
