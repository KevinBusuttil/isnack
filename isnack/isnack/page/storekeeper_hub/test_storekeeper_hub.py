# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import json
import unittest
from unittest.mock import patch, MagicMock

import frappe
from isnack.isnack.page.storekeeper_hub.storekeeper_hub import (
    get_items_per_stock_entry,
    get_combined_pallet_labels_html,
    print_combined_pallet_labels,
)


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


class TestPrintCombinedPalletLabels(unittest.TestCase):
    """Tests for print_combined_pallet_labels function."""

    def _make_factory_settings(self, fmt="SATO Label Print Collective", silent=False, printer=None):
        fs = MagicMock()
        fs.default_collective_label_print_format = fmt
        fs.default_label_print_format = "SATO Label Print"
        fs.enable_silent_printing = silent
        fs.default_label_printer = printer
        return fs

    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_single')
    def test_generates_printview_urls(self, mock_get_single, mock_get_value):
        """Each item should produce a /printview URL, not a custom API URL."""
        mock_get_single.return_value = self._make_factory_settings()

        items = [
            {
                'item_code': 'ITEM-001',
                'item_name': 'Test Item',
                'batch_no': 'BATCH-A',
                'uom': 'Kg',
                'qty': 10.0,
                'stock_entries': ['MAT-STE-2026-00001'],
            }
        ]
        result = print_combined_pallet_labels(items)

        self.assertIn('print_urls', result)
        self.assertEqual(len(result['print_urls']), 1)
        url = result['print_urls'][0]
        self.assertTrue(url.startswith('/printview'), f"Expected /printview URL, got: {url}")
        self.assertIn('Stock+Entry', url)
        self.assertIn('MAT-STE-2026-00001', url)
        self.assertIn('SED-ROW-001', url)
        self.assertIn('trigger_print=1', url)
        self.assertNotIn('/api/method/', url)
        self.assertIn('item_code=ITEM-001', url)
        self.assertIn('item_name=', url)
        self.assertIn('batch_no=BATCH-A', url)
        self.assertIn('uom=Kg', url)
        self.assertIn('qty=10.0', url)

    @patch('frappe.db.get_value', return_value=None)
    @patch('frappe.get_single')
    def test_generates_url_without_row_name_when_row_not_found(self, mock_get_single, mock_get_value):
        """When no matching row is found, a /printview URL without row_name is generated."""
        mock_get_single.return_value = self._make_factory_settings()

        items = [
            {
                'item_code': 'ITEM-999',
                'item_name': 'Unknown Item',
                'batch_no': None,
                'uom': 'Each',
                'qty': 5.0,
                'stock_entries': ['MAT-STE-2026-00001'],
            }
        ]
        result = print_combined_pallet_labels(items)

        self.assertEqual(len(result['print_urls']), 1)
        url = result['print_urls'][0]
        self.assertTrue(url.startswith('/printview'))
        self.assertNotIn('row_name', url)
        self.assertIn('item_code=ITEM-999', url)
        self.assertIn('qty=5.0', url)

    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_single')
    def test_skips_items_without_stock_entries(self, mock_get_single, mock_get_value):
        """Items without stock_entries are skipped and produce no URL."""
        mock_get_single.return_value = self._make_factory_settings()

        items = [
            {'item_code': 'ITEM-001', 'batch_no': 'B1', 'stock_entries': []},
            {'item_code': 'ITEM-002', 'batch_no': 'B2', 'stock_entries': ['MAT-STE-2026-00001']},
        ]
        result = print_combined_pallet_labels(items)

        self.assertEqual(len(result['print_urls']), 1)

    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_single')
    def test_uses_print_format_from_factory_settings(self, mock_get_single, mock_get_value):
        """The collective label print format from Factory Settings is used in the URL."""
        mock_get_single.return_value = self._make_factory_settings(fmt="SATO Label Print Collective")

        items = [
            {
                'item_code': 'ITEM-001',
                'batch_no': 'B1',
                'stock_entries': ['MAT-STE-2026-00001'],
            }
        ]
        result = print_combined_pallet_labels(items)

        self.assertIn('SATO+Label+Print+Collective', result['print_urls'][0])

    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_single')
    def test_returns_empty_list_for_empty_items(self, mock_get_single, mock_get_value):
        """Empty items list returns empty print_urls."""
        mock_get_single.return_value = self._make_factory_settings()

        result = print_combined_pallet_labels([])

        self.assertEqual(result['print_urls'], [])

    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_single')
    def test_accepts_json_string_input(self, mock_get_single, mock_get_value):
        """JSON string input for items is parsed correctly."""
        mock_get_single.return_value = self._make_factory_settings()

        items_json = json.dumps([
            {
                'item_code': 'ITEM-001',
                'batch_no': 'B1',
                'stock_entries': ['MAT-STE-2026-00001'],
            }
        ])
        result = print_combined_pallet_labels(items_json)

        self.assertEqual(len(result['print_urls']), 1)

    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_single')
    def test_returns_silent_printing_settings(self, mock_get_single, mock_get_value):
        """Silent printing settings from Factory Settings are returned."""
        mock_get_single.return_value = self._make_factory_settings(silent=True, printer='LabelPrinter1')

        items = [
            {
                'item_code': 'ITEM-001',
                'batch_no': 'B1',
                'stock_entries': ['MAT-STE-2026-00001'],
            }
        ]
        result = print_combined_pallet_labels(items)

        self.assertTrue(result['enable_silent_printing'])
        self.assertEqual(result['printer_name'], 'LabelPrinter1')


class TestGetCombinedPalletLabelsHtml(unittest.TestCase):
    """Tests for get_combined_pallet_labels_html function."""

    def _make_factory_settings(self, fmt="SATO Label Print Collective", silent=False, printer=None):
        fs = MagicMock()
        fs.default_collective_label_print_format = fmt
        fs.default_label_print_format = "SATO Label Print"
        fs.enable_silent_printing = silent
        fs.default_label_printer = printer
        return fs

    def _make_print_format(self, html="<p>{{ item_code }}</p>"):
        pf = MagicMock()
        pf.html = html
        return pf

    @patch('frappe.render_template', side_effect=lambda tmpl, ctx: tmpl.replace('{{ item_code }}', ctx.get('item_code', '')))
    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_doc')
    @patch('frappe.get_single')
    def test_returns_html_and_print_urls(self, mock_get_single, mock_get_doc, mock_get_value, mock_render):
        """Result contains both 'html' and 'print_urls' keys."""
        mock_get_single.return_value = self._make_factory_settings()
        mock_get_doc.return_value = self._make_print_format()

        items = [
            {
                'item_code': 'ITEM-001',
                'item_name': 'Test Item',
                'batch_no': 'BATCH-A',
                'uom': 'Kg',
                'qty': 10.0,
                'stock_entries': ['MAT-STE-2026-00001'],
            }
        ]
        result = get_combined_pallet_labels_html(items)

        self.assertIn('html', result)
        self.assertIn('print_urls', result)
        self.assertIn('enable_silent_printing', result)
        self.assertIn('printer_name', result)

    @patch('frappe.render_template', side_effect=lambda tmpl, ctx: tmpl.replace('{{ item_code }}', ctx.get('item_code', '')))
    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_doc')
    @patch('frappe.get_single')
    def test_html_contains_all_item_codes(self, mock_get_single, mock_get_doc, mock_get_value, mock_render):
        """Combined HTML contains rendered content for every item."""
        mock_get_single.return_value = self._make_factory_settings()
        mock_get_doc.return_value = self._make_print_format()

        items = [
            {'item_code': 'ITEM-001', 'batch_no': 'B1', 'uom': 'Kg', 'qty': 5.0, 'stock_entries': ['SE-001']},
            {'item_code': 'ITEM-002', 'batch_no': 'B2', 'uom': 'Nos', 'qty': 3.0, 'stock_entries': ['SE-002']},
        ]
        result = get_combined_pallet_labels_html(items)

        self.assertIn('ITEM-001', result['html'])
        self.assertIn('ITEM-002', result['html'])

    @patch('frappe.render_template', side_effect=lambda tmpl, ctx: tmpl)
    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_doc')
    @patch('frappe.get_single')
    def test_html_contains_page_break_between_multiple_labels(self, mock_get_single, mock_get_doc, mock_get_value, mock_render):
        """Combined HTML has a page-break CSS style between labels."""
        mock_get_single.return_value = self._make_factory_settings()
        mock_get_doc.return_value = self._make_print_format()

        items = [
            {'item_code': 'ITEM-001', 'batch_no': None, 'uom': 'Kg', 'qty': 1.0, 'stock_entries': ['SE-001']},
            {'item_code': 'ITEM-002', 'batch_no': None, 'uom': 'Kg', 'qty': 2.0, 'stock_entries': ['SE-002']},
        ]
        result = get_combined_pallet_labels_html(items)

        self.assertIn('break-after: page', result['html'])

    @patch('frappe.render_template', side_effect=lambda tmpl, ctx: tmpl)
    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_doc')
    @patch('frappe.get_single')
    def test_single_item_has_no_page_break(self, mock_get_single, mock_get_doc, mock_get_value, mock_render):
        """A single label should not have a trailing page-break style."""
        mock_get_single.return_value = self._make_factory_settings()
        mock_get_doc.return_value = self._make_print_format()

        items = [
            {'item_code': 'ITEM-001', 'batch_no': None, 'uom': 'Kg', 'qty': 1.0, 'stock_entries': ['SE-001']},
        ]
        result = get_combined_pallet_labels_html(items)

        self.assertNotIn('break-after: page', result['html'])

    @patch('frappe.render_template', side_effect=lambda tmpl, ctx: tmpl)
    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_doc')
    @patch('frappe.get_single')
    def test_html_contains_auto_print_script(self, mock_get_single, mock_get_doc, mock_get_value, mock_render):
        """Combined HTML includes the window.print() auto-print script."""
        mock_get_single.return_value = self._make_factory_settings()
        mock_get_doc.return_value = self._make_print_format()

        items = [
            {'item_code': 'ITEM-001', 'batch_no': None, 'uom': 'Kg', 'qty': 1.0, 'stock_entries': ['SE-001']},
        ]
        result = get_combined_pallet_labels_html(items)

        self.assertIn('window.print()', result['html'])

    @patch('frappe.render_template', side_effect=lambda tmpl, ctx: tmpl)
    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_doc')
    @patch('frappe.get_single')
    def test_print_urls_match_print_combined_pallet_labels(self, mock_get_single, mock_get_doc, mock_get_value, mock_render):
        """print_urls in the result should be the same /printview URLs as print_combined_pallet_labels."""
        mock_get_single.return_value = self._make_factory_settings()
        mock_get_doc.return_value = self._make_print_format()

        items = [
            {
                'item_code': 'ITEM-001',
                'item_name': 'Item One',
                'batch_no': 'B1',
                'uom': 'Kg',
                'qty': 5.0,
                'stock_entries': ['MAT-STE-2026-00001'],
            }
        ]
        result = get_combined_pallet_labels_html(items)

        self.assertEqual(len(result['print_urls']), 1)
        url = result['print_urls'][0]
        self.assertTrue(url.startswith('/printview'))
        self.assertIn('MAT-STE-2026-00001', url)
        self.assertIn('ITEM-001', url)
        self.assertIn('trigger_print=1', url)

    @patch('frappe.render_template', side_effect=lambda tmpl, ctx: tmpl)
    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_doc')
    @patch('frappe.get_single')
    def test_empty_items_returns_empty_html_and_urls(self, mock_get_single, mock_get_doc, mock_get_value, mock_render):
        """Empty items list results in no rendered labels and empty print_urls."""
        mock_get_single.return_value = self._make_factory_settings()
        mock_get_doc.return_value = self._make_print_format()

        result = get_combined_pallet_labels_html([])

        self.assertEqual(result['print_urls'], [])
        # html should still be a valid (empty body) HTML document
        self.assertIn('<!DOCTYPE html>', result['html'])
        self.assertNotIn('break-after', result['html'])

    @patch('frappe.render_template', side_effect=lambda tmpl, ctx: tmpl)
    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_doc')
    @patch('frappe.get_single')
    def test_accepts_json_string_input(self, mock_get_single, mock_get_doc, mock_get_value, mock_render):
        """JSON string input is parsed correctly."""
        mock_get_single.return_value = self._make_factory_settings()
        mock_get_doc.return_value = self._make_print_format()

        items_json = json.dumps([
            {'item_code': 'ITEM-001', 'batch_no': 'B1', 'stock_entries': ['SE-001']},
        ])
        result = get_combined_pallet_labels_html(items_json)

        self.assertEqual(len(result['print_urls']), 1)

    @patch('frappe.render_template', side_effect=lambda tmpl, ctx: tmpl)
    @patch('frappe.db.get_value', return_value='SED-ROW-001')
    @patch('frappe.get_doc')
    @patch('frappe.get_single')
    def test_returns_silent_printing_settings(self, mock_get_single, mock_get_doc, mock_get_value, mock_render):
        """Silent printing settings from Factory Settings are returned."""
        mock_get_single.return_value = self._make_factory_settings(silent=True, printer='LabelPrinter1')
        mock_get_doc.return_value = self._make_print_format()

        items = [
            {'item_code': 'ITEM-001', 'batch_no': 'B1', 'uom': 'Kg', 'qty': 1.0, 'stock_entries': ['SE-001']},
        ]
        result = get_combined_pallet_labels_html(items)

        self.assertTrue(result['enable_silent_printing'])
        self.assertEqual(result['printer_name'], 'LabelPrinter1')


if __name__ == '__main__':
    unittest.main()
