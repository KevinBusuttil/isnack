# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import json
import unittest
from unittest.mock import patch, MagicMock

import frappe
from isnack.api.mes_ops import print_pallet_label


class TestPrintPalletLabel(unittest.TestCase):
    """Tests for print_pallet_label function."""
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_print_pallet_label_success(self, mock_generate_url, mock_fs, mock_get_value, mock_exists, mock_require_roles):
        """Test successful pallet label creation."""
        # Mock Factory Settings
        mock_factory_settings = MagicMock()
        mock_factory_settings.default_fg_label_print_format = "FG Pallet Label"
        mock_factory_settings.enable_silent_printing = True
        mock_factory_settings.default_label_printer = "Label Printer 1"
        mock_fs.return_value = mock_factory_settings
        
        # Mock Work Order exists
        def exists_side_effect(doctype, docname=None):
            if doctype == "Work Order" and docname == "WO-001":
                return True
            if doctype == "Print Format" and docname == "FG Pallet Label":
                return True
            if doctype == "DocType":
                return False  # No Label Record or Label Print Job
            return False
        mock_exists.side_effect = exists_side_effect
        
        # Mock item details
        mock_get_value.return_value = {"item_name": "Test Item"}
        
        # Mock print URL generation
        mock_generate_url.return_value = "http://example.com/printview?doctype=Work%20Order&name=WO-001&format=FG%20Pallet%20Label&trigger_print=1"
        
        # Call function
        result = print_pallet_label(
            item_code="ITEM001",
            pallet_qty=2.5,
            pallet_type="EURO 1",
            work_orders='["WO-001"]',
            template="FG Pallet Label"
        )
        
        # Assertions
        self.assertTrue(result["success"])
        self.assertEqual(result["doctype"], "Work Order")
        self.assertEqual(result["docname"], "WO-001")
        self.assertEqual(result["print_format"], "FG Pallet Label")
        self.assertTrue(result["enable_silent_printing"])
        self.assertEqual(result["printer_name"], "Label Printer 1")
        self.assertIsNotNone(result["print_url"])
        self.assertEqual(len(result["print_urls"]), 1)
        self.assertIn("pallet_qty=2.5", result["print_url"])
        self.assertIn("pallet_type=EURO%201", result["print_url"])
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('frappe.new_doc')
    @patch('frappe.utils.now_datetime')
    @patch('frappe.session')
    def test_print_pallet_label_with_label_record(self, mock_session, mock_now, mock_new_doc, mock_generate_url, mock_fs, mock_get_value, mock_exists, mock_require_roles):
        """Test pallet label creation with Label Record."""
        # Mock session user
        mock_session.user = "test@example.com"
        mock_now.return_value = "2026-02-18 10:00:00"
        
        # Mock Factory Settings
        mock_factory_settings = MagicMock()
        mock_factory_settings.default_fg_label_print_format = "FG Pallet Label"
        mock_factory_settings.enable_silent_printing = False
        mock_factory_settings.default_label_printer = None
        mock_fs.return_value = mock_factory_settings
        
        # Mock Work Order exists
        def exists_side_effect(doctype, docname=None):
            if doctype == "Work Order" and docname == "WO-001":
                return True
            if doctype == "Print Format" and docname == "FG Pallet Label":
                return True
            if doctype == "DocType":
                if docname == "Label Record":
                    return True
                if docname == "Label Print Job":
                    return True
                return False
            return False
        mock_exists.side_effect = exists_side_effect
        
        # Mock item details
        mock_get_value.return_value = {"item_name": "Test Item"}
        
        # Mock print URL generation
        mock_generate_url.return_value = "http://example.com/printview"
        
        # Mock Label Record and Print Job
        mock_label_record = MagicMock()
        mock_label_record.name = "LBL-001"
        mock_print_job = MagicMock()
        mock_print_job.name = "PJ-001"
        
        def new_doc_side_effect(doctype):
            if doctype == "Label Record":
                return mock_label_record
            if doctype == "Label Print Job":
                return mock_print_job
            return MagicMock()
        mock_new_doc.side_effect = new_doc_side_effect
        
        # Call function
        result = print_pallet_label(
            item_code="ITEM001",
            pallet_qty=2.5,
            pallet_type="EURO 1",
            work_orders='["WO-001", "WO-002"]',
            template=None  # Should use default from Factory Settings
        )
        
        # Assertions
        self.assertTrue(result["success"])
        self.assertEqual(result["label_record"], "LBL-001")
        self.assertFalse(result["enable_silent_printing"])
        self.assertIsNone(result["printer_name"])
        
        # Verify Label Record was created with correct data
        mock_label_record.insert.assert_called_once()
        self.assertEqual(mock_label_record.label_template, "FG Pallet Label")
        self.assertEqual(mock_label_record.template_engine, "Jinja")
        self.assertEqual(mock_label_record.quantity, 2.5)
        self.assertEqual(mock_label_record.item_code, "ITEM001")
        self.assertEqual(mock_label_record.item_name, "Test Item")
        self.assertEqual(mock_label_record.source_doctype, "Work Order")
        self.assertEqual(mock_label_record.source_docname, "WO-001")
        
        # Verify payload includes pallet info
        payload_dict = json.loads(mock_label_record.payload)
        self.assertEqual(payload_dict["pallet_type"], "EURO 1")
        self.assertEqual(payload_dict["work_orders"], ["WO-001", "WO-002"])
        
        # Verify Print Job was created
        mock_print_job.insert.assert_called_once()
        self.assertEqual(mock_print_job.label_record, "LBL-001")
        self.assertEqual(mock_print_job.quantity, 2.5)
        self.assertEqual(mock_print_job.status, "Queued")
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.throw')
    def test_print_pallet_label_no_work_orders(self, mock_throw, mock_require_roles):
        """Test that missing work orders throws error."""
        mock_throw.side_effect = frappe.ValidationError
        
        with self.assertRaises(frappe.ValidationError):
            print_pallet_label(
                item_code="ITEM001",
                pallet_qty=2.5,
                pallet_type="EURO 1",
                work_orders='[]',
                template="FG Pallet Label"
            )
        
        mock_throw.assert_called()
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.throw')
    def test_print_pallet_label_invalid_work_order(self, mock_throw, mock_exists, mock_require_roles):
        """Test that invalid work order throws error."""
        mock_exists.return_value = False
        mock_throw.side_effect = frappe.ValidationError
        
        with self.assertRaises(frappe.ValidationError):
            print_pallet_label(
                item_code="ITEM001",
                pallet_qty=2.5,
                pallet_type="EURO 1",
                work_orders='["INVALID-WO"]',
                template="FG Pallet Label"
            )
        
        mock_throw.assert_called()
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('isnack.api.mes_ops._fs')
    @patch('frappe.throw')
    def test_print_pallet_label_no_template(self, mock_throw, mock_fs, mock_exists, mock_require_roles):
        """Test that missing template configuration throws error."""
        # Mock Factory Settings with no templates
        mock_factory_settings = MagicMock()
        mock_factory_settings.default_fg_label_print_format = None
        mock_factory_settings.default_label_print_format = None
        mock_factory_settings.default_label_template = None
        mock_fs.return_value = mock_factory_settings
        
        # Mock Work Order exists
        mock_exists.return_value = True
        mock_throw.side_effect = frappe.ValidationError
        
        with self.assertRaises(frappe.ValidationError):
            print_pallet_label(
                item_code="ITEM001",
                pallet_qty=2.5,
                pallet_type="EURO 1",
                work_orders='["WO-001"]',
                template=None
            )
        
        mock_throw.assert_called()
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_print_pallet_label_multiple_work_orders(self, mock_generate_url, mock_fs, mock_get_value, mock_exists, mock_require_roles):
        """Test pallet label with multiple work orders uses first for traceability."""
        # Mock Factory Settings
        mock_factory_settings = MagicMock()
        mock_factory_settings.default_fg_label_print_format = "FG Pallet Label"
        mock_factory_settings.enable_silent_printing = False
        mock_factory_settings.default_label_printer = None
        mock_fs.return_value = mock_factory_settings
        
        # Mock Work Orders exist
        def exists_side_effect(doctype, docname=None):
            if doctype == "Work Order" and docname in ["WO-001", "WO-002", "WO-003"]:
                return True
            if doctype == "Print Format" and docname == "FG Pallet Label":
                return True
            if doctype == "DocType":
                return False
            return False
        mock_exists.side_effect = exists_side_effect
        
        # Mock item details
        mock_get_value.return_value = {"item_name": "Test Item"}
        
        # Mock print URL generation
        mock_generate_url.return_value = "http://example.com/printview"
        
        # Call function with multiple work orders
        result = print_pallet_label(
            item_code="ITEM001",
            pallet_qty=10.0,
            pallet_type="EURO 4",
            work_orders='["WO-001", "WO-002", "WO-003"]',
            template="FG Pallet Label"
        )
        
        # Should use first work order
        self.assertEqual(result["docname"], "WO-001")
        mock_generate_url.assert_called_once_with("Work Order", "WO-001", "FG Pallet Label")
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_print_pallet_label_fallback_template(self, mock_generate_url, mock_fs, mock_get_value, mock_exists, mock_require_roles):
        """Test template fallback from default_fg to default_label_print_format to default_label_template."""
        # Mock Factory Settings with fallback template
        mock_factory_settings = MagicMock()
        mock_factory_settings.default_fg_label_print_format = None
        mock_factory_settings.default_label_print_format = "Generic Label"
        mock_factory_settings.default_label_template = None
        mock_factory_settings.enable_silent_printing = False
        mock_factory_settings.default_label_printer = None
        mock_fs.return_value = mock_factory_settings
        
        # Mock Work Order exists
        def exists_side_effect(doctype, docname=None):
            if doctype == "Work Order" and docname == "WO-001":
                return True
            if doctype == "Print Format" and docname == "Generic Label":
                return True
            if doctype == "DocType":
                return False
            return False
        mock_exists.side_effect = exists_side_effect
        
        # Mock item details
        mock_get_value.return_value = {"item_name": "Test Item"}
        
        # Mock print URL generation
        mock_generate_url.return_value = "http://example.com/printview"
        
        # Call function without template (should use fallback)
        result = print_pallet_label(
            item_code="ITEM001",
            pallet_qty=5.0,
            pallet_type="EURO 1",
            work_orders='["WO-001"]',
            template=None
        )
        
        # Should use fallback template
        self.assertEqual(result["print_format"], "Generic Label")


if __name__ == "__main__":
    unittest.main()
