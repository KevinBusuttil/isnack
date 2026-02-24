# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import json
import unittest
from unittest.mock import patch, MagicMock

import frappe
from isnack.isnack.page.storekeeper_hub.storekeeper_hub import get_items_per_stock_entry


class TestGetItemsPerStockEntry(unittest.TestCase):
    """Tests for get_items_per_stock_entry function."""

    @patch('frappe.db.sql')
    def test_returns_empty_dict_for_empty_input(self, mock_sql):
        """Test that empty stock_entries input returns empty dict."""
        result = get_items_per_stock_entry([])
        self.assertEqual(result, {})
        mock_sql.assert_not_called()

    @patch('frappe.db.sql')
    def test_returns_empty_dict_for_empty_json_string(self, mock_sql):
        """Test that empty JSON string input returns empty dict."""
        result = get_items_per_stock_entry('[]')
        self.assertEqual(result, {})
        mock_sql.assert_not_called()

    @patch('frappe.db.sql')
    def test_accepts_json_string_input(self, mock_sql):
        """Test that JSON string input is parsed correctly."""
        mock_sql.return_value = [
            {
                'parent': 'MAT-STE-2026-00001',
                'item_code': 'ITEM-001',
                'item_name': 'Test Item',
                'batch_no': None,
                'uom': 'Kg',
                'qty': 10.0,
            }
        ]
        result = get_items_per_stock_entry('["MAT-STE-2026-00001"]')
        self.assertIn('MAT-STE-2026-00001', result)
        self.assertEqual(len(result['MAT-STE-2026-00001']), 1)

    @patch('frappe.db.sql')
    def test_groups_items_by_stock_entry(self, mock_sql):
        """Test that items are correctly grouped by stock entry name."""
        mock_sql.return_value = [
            {
                'parent': 'MAT-STE-2026-00001',
                'item_code': 'ITEM-001',
                'item_name': 'Item One',
                'batch_no': 'BATCH-A',
                'uom': 'Kg',
                'qty': 5.0,
            },
            {
                'parent': 'MAT-STE-2026-00001',
                'item_code': 'ITEM-002',
                'item_name': 'Item Two',
                'batch_no': None,
                'uom': 'Nos',
                'qty': 20.0,
            },
            {
                'parent': 'MAT-STE-2026-00002',
                'item_code': 'ITEM-003',
                'item_name': 'Item Three',
                'batch_no': 'BATCH-B',
                'uom': 'Kg',
                'qty': 15.0,
            },
        ]

        result = get_items_per_stock_entry(['MAT-STE-2026-00001', 'MAT-STE-2026-00002'])

        self.assertIn('MAT-STE-2026-00001', result)
        self.assertIn('MAT-STE-2026-00002', result)
        self.assertEqual(len(result['MAT-STE-2026-00001']), 2)
        self.assertEqual(len(result['MAT-STE-2026-00002']), 1)

    @patch('frappe.db.sql')
    def test_parent_key_removed_from_item_rows(self, mock_sql):
        """Test that 'parent' key is not present in the returned item dicts."""
        mock_sql.return_value = [
            {
                'parent': 'MAT-STE-2026-00001',
                'item_code': 'ITEM-001',
                'item_name': 'Item One',
                'batch_no': None,
                'uom': 'Kg',
                'qty': 5.0,
            }
        ]

        result = get_items_per_stock_entry(['MAT-STE-2026-00001'])
        item = result['MAT-STE-2026-00001'][0]
        self.assertNotIn('parent', item)
        self.assertEqual(item['item_code'], 'ITEM-001')
        self.assertEqual(item['item_name'], 'Item One')
        self.assertIsNone(item['batch_no'])
        self.assertEqual(item['uom'], 'Kg')
        self.assertEqual(item['qty'], 5.0)

    @patch('frappe.db.sql')
    def test_qty_is_converted_to_float(self, mock_sql):
        """Test that qty values are returned as floats."""
        mock_sql.return_value = [
            {
                'parent': 'MAT-STE-2026-00001',
                'item_code': 'ITEM-001',
                'item_name': 'Item One',
                'batch_no': None,
                'uom': 'Kg',
                'qty': '12',  # string from DB
            }
        ]

        result = get_items_per_stock_entry(['MAT-STE-2026-00001'])
        item = result['MAT-STE-2026-00001'][0]
        self.assertIsInstance(item['qty'], float)
        self.assertEqual(item['qty'], 12.0)

    @patch('frappe.db.sql')
    def test_returns_empty_for_se_with_no_submitted_items(self, mock_sql):
        """Test that an SE with no submitted items returns empty result."""
        mock_sql.return_value = []

        result = get_items_per_stock_entry(['MAT-STE-2026-00001'])
        self.assertEqual(result, {})

    @patch('frappe.db.sql')
    def test_comma_separated_string_input(self, mock_sql):
        """Test that comma-separated string input is handled."""
        mock_sql.return_value = [
            {
                'parent': 'MAT-STE-2026-00001',
                'item_code': 'ITEM-001',
                'item_name': 'Item One',
                'batch_no': None,
                'uom': 'Kg',
                'qty': 5.0,
            }
        ]
        result = get_items_per_stock_entry('MAT-STE-2026-00001, MAT-STE-2026-00002')
        self.assertIn('MAT-STE-2026-00001', result)

    @patch('frappe.db.sql')
    def test_sql_query_uses_correct_params(self, mock_sql):
        """Test that the SQL query is called with the correct parameters."""
        mock_sql.return_value = []
        se_list = ['MAT-STE-2026-00001', 'MAT-STE-2026-00002']

        get_items_per_stock_entry(se_list)

        mock_sql.assert_called_once()
        call_args = mock_sql.call_args
        params = call_args[0][1]
        self.assertIn('stock_entries', params)
        self.assertEqual(set(params['stock_entries']), set(se_list))


if __name__ == '__main__':
    unittest.main()
