# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import json
import unittest
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch, MagicMock

import frappe
from isnack.api.mes_ops import (
    _is_fg_item_group,
    _pallet_label_print_summary,
    combine_label_records,
    get_pallet_label_data,
    get_pallet_label_data_for_production_plan,
    print_label,
    print_label_record,
    print_pallet_label,
    list_label_records,
)


def _fake_print_url(source_doctype, source_docname, print_format, row_name=None,
                    batch_no=None, carton_qty=None, pallet_qty=None, pallet_type=None):
    """Stand-in for _generate_print_url that assembles the same query string.

    The real builder is patched out in these tests, so this mirrors its
    signature, parameter order and escaping. A test can then assert on the URL
    strings a print path hands back, not only on the builder's call arguments.
    """
    url = (
        f"/printview?doctype={frappe.utils.quote(source_doctype)}"
        f"&name={frappe.utils.quote(source_docname)}"
        f"&format={frappe.utils.quote(print_format)}"
    )
    for key, value in (
        ("row_name", row_name),
        ("batch_no", batch_no),
        ("carton_qty", carton_qty),
        ("pallet_qty", pallet_qty),
        ("pallet_type", pallet_type),
    ):
        if value is not None:
            url += f"&{key}={frappe.utils.quote(str(value))}"
    return f"http://example.com{url}&trigger_print=1"


class TestPrintPalletLabel(unittest.TestCase):
    """Tests for print_pallet_label function."""
    
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_print_pallet_label_success(self, mock_generate_url, mock_fs, mock_get_value, mock_exists, mock_require_roles, mock_fg_batch):
        """Test successful pallet label creation."""
        mock_fg_batch.return_value = "BBB-111"

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
        mock_generate_url.side_effect = _fake_print_url

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
        # pallet_qty=2.5 should return ceil(2.5) = 3 URLs
        self.assertEqual(len(result["print_urls"]), 3)
        self.assertIn("pallet_qty=2.5", result["print_url"])
        self.assertIn("pallet_type=EURO%201", result["print_url"])

    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_print_pallet_label_carton_qty_distribution(self, mock_generate_url, mock_fs, mock_get_value, mock_exists, mock_require_roles, mock_fg_batch):
        """carton_qty is split per pallet: 1000 cartons / 15.385 pallets -> 15x65 + 1x25."""
        mock_fg_batch.return_value = "BBB-111"
        mock_factory_settings = MagicMock()
        mock_factory_settings.default_fg_label_print_format = "FG Pallet Label"
        mock_factory_settings.enable_silent_printing = False
        mock_factory_settings.default_label_printer = None
        mock_fs.return_value = mock_factory_settings

        def exists_side_effect(doctype, docname=None):
            if doctype == "Work Order" and docname == "WO-001":
                return True
            if doctype == "Print Format" and docname == "FG Pallet Label":
                return True
            return False
        mock_exists.side_effect = exists_side_effect

        mock_get_value.return_value = {"item_name": "Test Item"}
        mock_generate_url.side_effect = _fake_print_url

        result = print_pallet_label(
            item_code="ITEM001",
            pallet_qty=1000.0 / 65.0,
            pallet_type="EURO 1",
            work_orders='["WO-001"]',
            template="FG Pallet Label",
            carton_qty=1000,
        )

        urls = result["print_urls"]
        self.assertEqual(len(urls), 16)
        self.assertEqual(sum(1 for u in urls if "carton_qty=65&" in u), 15)
        self.assertEqual(sum(1 for u in urls if "carton_qty=25&" in u), 1)

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('frappe.new_doc')
    @patch('frappe.utils.now_datetime')
    @patch('frappe.session')
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    def test_print_pallet_label_with_label_record(self, mock_fg_batch, mock_session, mock_now, mock_new_doc, mock_generate_url, mock_fs, mock_get_value, mock_exists, mock_require_roles):
        """Test pallet label creation with Label Record."""
        mock_fg_batch.return_value = "BBB-111"

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
        
        # Verify sources child table was populated
        self.assertEqual(mock_label_record.append.call_count, 2)
        mock_label_record.append.assert_any_call("sources", {"source_doctype": "Work Order", "source_docname": "WO-001"})
        mock_label_record.append.assert_any_call("sources", {"source_doctype": "Work Order", "source_docname": "WO-002"})
        
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
    
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('isnack.api.mes_ops._fs')
    @patch('frappe.throw')
    def test_print_pallet_label_no_template(self, mock_throw, mock_fs, mock_exists, mock_require_roles, mock_fg_batch):
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
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    def test_print_pallet_label_multiple_work_orders(self, mock_fg_batch, mock_generate_url, mock_fs, mock_get_value, mock_exists, mock_require_roles):
        """Test pallet label with multiple work orders uses first for traceability."""
        mock_fg_batch.return_value = "BBB-111"

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
        # No carton_qty was supplied, so the legacy single-URL path builds one
        # URL and repeats it once per pallet.
        mock_generate_url.assert_called_once_with(
            "Work Order",
            "WO-001",
            "FG Pallet Label",
            batch_no="BBB-111",
            pallet_qty=10.0,
            pallet_type="EURO 4",
        )
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    def test_print_pallet_label_fallback_template(self, mock_fg_batch, mock_generate_url, mock_fs, mock_get_value, mock_exists, mock_require_roles):
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
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    def test_print_pallet_label_single_pallet(self, mock_fg_batch, mock_generate_url, mock_fs, mock_get_value, mock_exists, mock_require_roles):
        """Test pallet_qty=1.0 returns exactly 1 URL."""
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
                return False
            return False
        mock_exists.side_effect = exists_side_effect
        
        # Mock item details
        mock_get_value.return_value = {"item_name": "Test Item"}
        
        # Mock print URL generation
        mock_generate_url.return_value = "http://example.com/printview"
        
        # Call function with pallet_qty=1.0
        result = print_pallet_label(
            item_code="ITEM001",
            pallet_qty=1.0,
            pallet_type="EURO 1",
            work_orders='["WO-001"]',
            template="FG Pallet Label"
        )
        
        # Should return exactly 1 URL
        self.assertEqual(len(result["print_urls"]), 1)
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    def test_print_pallet_label_multiple_pallets(self, mock_fg_batch, mock_generate_url, mock_fs, mock_get_value, mock_exists, mock_require_roles):
        """Test pallet_qty=5.0 returns exactly 5 URLs."""
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
                return False
            return False
        mock_exists.side_effect = exists_side_effect
        
        # Mock item details
        mock_get_value.return_value = {"item_name": "Test Item"}
        
        # Mock print URL generation
        mock_generate_url.return_value = "http://example.com/printview"
        
        # Call function with pallet_qty=5.0
        result = print_pallet_label(
            item_code="ITEM001",
            pallet_qty=5.0,
            pallet_type="EURO 1",
            work_orders='["WO-001"]',
            template="FG Pallet Label"
        )
        
        # Should return exactly 5 URLs
        self.assertEqual(len(result["print_urls"]), 5)


class TestListLabelRecords(unittest.TestCase):
    """Tests for list_label_records function."""
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.sql')
    def test_list_label_records_multi_wo(self, mock_sql, mock_exists, mock_require_roles):
        """Test that list_label_records queries via child table for multi-WO support."""
        # Mock DocType exists
        def exists_side_effect(doctype, docname=None):
            if doctype == "DocType" and docname == "Label Record":
                return True
            return False
        mock_exists.side_effect = exists_side_effect
        
        # Mock SQL query results
        mock_records = [
            {
                "name": "LBL-001",
                "label_template": "FG Pallet Label",
                "quantity": 2.5,
                "item_code": "ITEM001",
                "item_name": "Test Item",
                "batch_no": None,
                "creation": "2026-02-18 10:00:00"
            }
        ]
        mock_sql.return_value = mock_records
        
        # Call function with WO-002 (not the first work order)
        result = list_label_records("WO-002")
        
        # Verify SQL was called with correct query
        mock_sql.assert_called_once()
        call_args = mock_sql.call_args
        sql_query = call_args[0][0]
        
        # Verify query uses new sources child table
        self.assertIn("INNER JOIN `tabLabel Record Source` lrs", sql_query)
        self.assertIn("lrs.source_doctype = 'Work Order'", sql_query)
        self.assertIn("lrs.source_docname = %(work_order)s", sql_query)
        # Verify old fields are not present
        self.assertNotIn("lr.source_docname", sql_query)
        self.assertNotIn("Label Record Work Order", sql_query)
        
        # Verify work_order parameter was passed (positional values argument)
        self.assertEqual(call_args[0][1], {"work_order": "WO-002"})

        # Verify as_dict=True
        self.assertTrue(call_args[1].get("as_dict"))
        
        # Verify result
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "LBL-001")


def _exists_stub(audit_doctypes=("Label Record", "Packed Carton")):
    """Build a frappe.db.exists stub for the label print paths.

    Work Orders WO-001..WO-003 and the label print formats used below exist;
    `audit_doctypes` lists the optional DocTypes treated as installed. Label
    Print Job is left out by default so the print paths never reach
    frappe.session.
    """
    def _exists(doctype, docname=None):
        if doctype == "Work Order":
            return docname in ("WO-001", "WO-002", "WO-003")
        if doctype == "Print Format":
            return docname in ("FG Pallet Label", "SATO FG Label Print")
        if doctype == "DocType":
            return docname in audit_doctypes
        return False
    return _exists


def _new_doc_recorder(names=None):
    """frappe.new_doc stub plus the docs it handed out.

    Returns (side_effect, created): one MagicMock per DocType, kept in
    `created` so a test can assert on the fields the print path stamped on it.
    """
    names = names or {}
    created = {}

    def _new_doc(doctype):
        doc = created.get(doctype)
        if doc is None:
            doc = MagicMock()
            doc.name = names.get(doctype, doctype)
            created[doctype] = doc
        return doc

    return _new_doc, created


class TestPrintPalletLabelBatch(unittest.TestCase):
    """The batch resolved from the pallet's Work Orders reaches the record and every URL."""

    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('frappe.new_doc')
    def test_print_pallet_label_stamps_the_resolved_batch_on_the_label_record(
            self, mock_new_doc, mock_generate_url, mock_fs, mock_get_value, mock_exists,
            mock_require_roles, mock_fg_batch):
        """The Label Record stores the resolved batch instead of being left NULL."""
        mock_fg_batch.return_value = "BBB-111"

        mock_factory_settings = MagicMock()
        mock_factory_settings.default_fg_label_print_format = "FG Pallet Label"
        mock_factory_settings.enable_silent_printing = False
        mock_factory_settings.default_label_printer = None
        mock_fs.return_value = mock_factory_settings

        mock_exists.side_effect = _exists_stub()
        mock_get_value.return_value = {"item_name": "Test Item"}
        mock_generate_url.side_effect = _fake_print_url

        new_doc, created = _new_doc_recorder({"Label Record": "LBL-001"})
        mock_new_doc.side_effect = new_doc

        result = print_pallet_label(
            item_code="FG10011",
            pallet_qty=1.0,
            pallet_type="EURO 1",
            work_orders='["WO-001"]',
            template="FG Pallet Label",
            carton_qty=27,
        )

        self.assertEqual(result["label_record"], "LBL-001")
        self.assertEqual(created["Label Record"].batch_no, "BBB-111")
        created["Label Record"].insert.assert_called_once()

    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_print_pallet_label_resolves_the_batch_from_every_work_order_on_the_pallet(
            self, mock_generate_url, mock_fs, mock_get_value, mock_exists,
            mock_require_roles, mock_fg_batch):
        """A pallet spanning several Work Orders resolves against the whole list, not just the first."""
        mock_fg_batch.return_value = "BBB-111"

        mock_factory_settings = MagicMock()
        mock_factory_settings.default_fg_label_print_format = "FG Pallet Label"
        mock_factory_settings.enable_silent_printing = False
        mock_factory_settings.default_label_printer = None
        mock_fs.return_value = mock_factory_settings

        mock_exists.side_effect = _exists_stub(())
        mock_get_value.return_value = {"item_name": "Test Item"}
        mock_generate_url.side_effect = _fake_print_url

        print_pallet_label(
            item_code="FG10011",
            pallet_qty=1.0,
            pallet_type="EURO 1",
            work_orders='["WO-001", "WO-002", "WO-003"]',
            template="FG Pallet Label",
        )

        mock_fg_batch.assert_called_once_with(["WO-001", "WO-002", "WO-003"])

    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_print_pallet_label_puts_batch_no_on_every_split_carton_url(
            self, mock_generate_url, mock_fs, mock_get_value, mock_exists,
            mock_require_roles, mock_fg_batch):
        """Each of the 16 per-pallet URLs carries the batch, not only the first one."""
        mock_fg_batch.return_value = "BBB-111"

        mock_factory_settings = MagicMock()
        mock_factory_settings.default_fg_label_print_format = "FG Pallet Label"
        mock_factory_settings.enable_silent_printing = False
        mock_factory_settings.default_label_printer = None
        mock_fs.return_value = mock_factory_settings

        mock_exists.side_effect = _exists_stub(())
        mock_get_value.return_value = {"item_name": "Test Item"}
        mock_generate_url.side_effect = _fake_print_url

        result = print_pallet_label(
            item_code="FG10011",
            pallet_qty=1000.0 / 65.0,
            pallet_type="EURO 1",
            work_orders='["WO-001"]',
            template="FG Pallet Label",
            carton_qty=1000,
        )

        urls = result["print_urls"]
        self.assertEqual(len(urls), 16)
        self.assertEqual(sum(1 for u in urls if "batch_no=BBB-111" in u), 16)
        self.assertIn("batch_no=BBB-111", result["print_url"])
        self.assertEqual(
            [call.kwargs["batch_no"] for call in mock_generate_url.call_args_list],
            ["BBB-111"] * 16,
        )

    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_print_pallet_label_puts_batch_no_on_the_repeated_url_when_no_carton_qty(
            self, mock_generate_url, mock_fs, mock_get_value, mock_exists,
            mock_require_roles, mock_fg_batch):
        """The legacy one-URL-per-pallet path carries the batch on every copy too."""
        mock_fg_batch.return_value = "BBB-111"

        mock_factory_settings = MagicMock()
        mock_factory_settings.default_fg_label_print_format = "FG Pallet Label"
        mock_factory_settings.enable_silent_printing = False
        mock_factory_settings.default_label_printer = None
        mock_fs.return_value = mock_factory_settings

        mock_exists.side_effect = _exists_stub(())
        mock_get_value.return_value = {"item_name": "Test Item"}
        mock_generate_url.side_effect = _fake_print_url

        result = print_pallet_label(
            item_code="FG10011",
            pallet_qty=3.0,
            pallet_type="EURO 1",
            work_orders='["WO-001"]',
            template="FG Pallet Label",
        )

        self.assertEqual(len(result["print_urls"]), 3)
        for call in mock_generate_url.call_args_list:
            self.assertEqual(call.kwargs["batch_no"], "BBB-111")
        for url in result["print_urls"]:
            self.assertIn("batch_no=BBB-111", url)

    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('frappe.new_doc')
    def test_print_pallet_label_leaves_the_batch_off_when_the_work_orders_disagree(
            self, mock_new_doc, mock_generate_url, mock_fs, mock_get_value, mock_exists,
            mock_require_roles, mock_fg_batch):
        """Work Orders that disagree leave the record NULL and send an EMPTY batch_no.

        The parameter is sent rather than omitted so the print format can tell
        "the server looked and found no single batch" from "nobody asked": an
        omitted parameter makes the format resolve the batch itself, which would
        stamp the first Work Order's batch on a mixed pallet.
        """
        mock_fg_batch.return_value = None

        mock_factory_settings = MagicMock()
        mock_factory_settings.default_fg_label_print_format = "FG Pallet Label"
        mock_factory_settings.enable_silent_printing = False
        mock_factory_settings.default_label_printer = None
        mock_fs.return_value = mock_factory_settings

        mock_exists.side_effect = _exists_stub()
        mock_get_value.return_value = {"item_name": "Test Item"}
        mock_generate_url.side_effect = _fake_print_url

        new_doc, created = _new_doc_recorder({"Label Record": "LBL-002"})
        mock_new_doc.side_effect = new_doc

        result = print_pallet_label(
            item_code="FG10011",
            pallet_qty=1.0,
            pallet_type="EURO 1",
            work_orders='["WO-001", "WO-002"]',
            template="FG Pallet Label",
        )

        self.assertIsNone(created["Label Record"].batch_no)
        self.assertEqual(mock_generate_url.call_args.kwargs["batch_no"], "")
        self.assertIn("batch_no=&", result["print_url"])


class TestPrintLabelBatch(unittest.TestCase):
    """The batch resolved from the Work Order reaches the record, the carton and the URL."""

    def _wo_doc(self):
        """A Work Order doc restricted to the fields tabWork Order actually has.

        The table has no batch_no column, so `spec` makes any attempt to read a
        batch off the document raise AttributeError instead of silently
        yielding None the way the production bug did.
        """
        wo = MagicMock(spec=["name", "production_item", "item_name", "qty"])
        wo.name = "WO-001"
        wo.production_item = "FG10011"
        wo.item_name = "Crisps 100g"
        wo.qty = 300
        return wo

    def _factory_settings(self):
        fs = MagicMock()
        fs.default_fg_label_print_format = "SATO FG Label Print"
        fs.enable_silent_printing = False
        fs.default_label_printer = None
        return fs

    @patch('isnack.api.mes_ops.fg_batch_for_work_order')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops._is_fg')
    @patch('frappe.get_doc')
    @patch('frappe.db.exists')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('frappe.new_doc')
    def test_print_label_stamps_the_resolved_batch_on_the_label_record(
            self, mock_new_doc, mock_generate_url, mock_fs, mock_exists, mock_get_doc,
            mock_is_fg, mock_require_roles, mock_fg_batch):
        """The carton Label Record stores the resolved batch instead of being left NULL."""
        mock_fg_batch.return_value = "BBB-111"
        mock_is_fg.return_value = True
        mock_get_doc.return_value = self._wo_doc()
        mock_fs.return_value = self._factory_settings()
        mock_exists.side_effect = _exists_stub()
        mock_generate_url.side_effect = _fake_print_url

        new_doc, created = _new_doc_recorder({"Label Record": "LBL-003"})
        mock_new_doc.side_effect = new_doc

        result = print_label(
            carton_qty=27,
            template="SATO FG Label Print",
            work_order="WO-001",
        )

        self.assertEqual(result["label_record"], "LBL-003")
        self.assertEqual(created["Label Record"].batch_no, "BBB-111")
        created["Label Record"].insert.assert_called_once()

    @patch('isnack.api.mes_ops.fg_batch_for_work_order')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops._is_fg')
    @patch('frappe.get_doc')
    @patch('frappe.db.exists')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('frappe.new_doc')
    def test_print_label_stamps_the_resolved_batch_on_the_packed_carton(
            self, mock_new_doc, mock_generate_url, mock_fs, mock_exists, mock_get_doc,
            mock_is_fg, mock_require_roles, mock_fg_batch):
        """The Packed Carton booked for the label records the same batch as the label."""
        mock_fg_batch.return_value = "BBB-111"
        mock_is_fg.return_value = True
        mock_get_doc.return_value = self._wo_doc()
        mock_fs.return_value = self._factory_settings()
        mock_exists.side_effect = _exists_stub()
        mock_generate_url.side_effect = _fake_print_url

        new_doc, created = _new_doc_recorder({"Label Record": "LBL-003"})
        mock_new_doc.side_effect = new_doc

        print_label(
            carton_qty=27,
            template="SATO FG Label Print",
            work_order="WO-001",
        )

        carton = created["Packed Carton"]
        self.assertEqual(carton.batch_no, "BBB-111")
        self.assertEqual(carton.work_order, "WO-001")
        self.assertEqual(carton.item_code, "FG10011")
        carton.insert.assert_called_once()

    @patch('isnack.api.mes_ops.fg_batch_for_work_order')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops._is_fg')
    @patch('frappe.get_doc')
    @patch('frappe.db.exists')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_print_label_puts_batch_no_and_carton_qty_on_the_print_url(
            self, mock_generate_url, mock_fs, mock_exists, mock_get_doc,
            mock_is_fg, mock_require_roles, mock_fg_batch):
        """The single carton URL carries the batch and the cartons on that label."""
        mock_fg_batch.return_value = "BBB-111"
        mock_is_fg.return_value = True
        mock_get_doc.return_value = self._wo_doc()
        mock_fs.return_value = self._factory_settings()
        mock_exists.side_effect = _exists_stub(())
        mock_generate_url.side_effect = _fake_print_url

        result = print_label(
            carton_qty=27,
            template="SATO FG Label Print",
            work_order="WO-001",
        )

        self.assertIn("batch_no=BBB-111", result["print_url"])
        self.assertIn("carton_qty=27", result["print_url"])
        mock_generate_url.assert_called_once_with(
            "Work Order",
            "WO-001",
            "SATO FG Label Print",
            batch_no="BBB-111",
            carton_qty=27,
        )

    @patch('isnack.api.mes_ops.fg_batch_for_work_order')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops._is_fg')
    @patch('frappe.get_doc')
    @patch('frappe.db.exists')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_print_label_resolves_the_batch_from_the_work_order_name_not_the_document(
            self, mock_generate_url, mock_fs, mock_exists, mock_get_doc,
            mock_is_fg, mock_require_roles, mock_fg_batch):
        """The batch comes from the resolver; the Work Order doc is never read for one."""
        mock_fg_batch.return_value = "BBB-111"
        mock_is_fg.return_value = True
        mock_get_doc.return_value = self._wo_doc()
        mock_fs.return_value = self._factory_settings()
        mock_exists.side_effect = _exists_stub(())
        mock_generate_url.side_effect = _fake_print_url

        print_label(
            carton_qty=27,
            template="SATO FG Label Print",
            work_order="WO-001",
        )

        # _wo_doc() is spec'd without batch_no: reading one off the Work Order
        # would have raised AttributeError before we got here.
        mock_fg_batch.assert_called_once_with("WO-001")

    @patch('isnack.api.mes_ops.fg_batch_for_work_order')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops._is_fg')
    @patch('frappe.get_doc')
    @patch('frappe.db.exists')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('frappe.new_doc')
    def test_print_label_leaves_the_batch_off_when_the_work_order_has_none(
            self, mock_new_doc, mock_generate_url, mock_fs, mock_exists, mock_get_doc,
            mock_is_fg, mock_require_roles, mock_fg_batch):
        """An unresolved batch leaves record and carton NULL and sends an EMPTY batch_no.

        As for a mixed pallet, the empty parameter is what stops the print format
        from re-resolving and labelling a batch the server declined to print.
        """
        mock_fg_batch.return_value = None
        mock_is_fg.return_value = True
        mock_get_doc.return_value = self._wo_doc()
        mock_fs.return_value = self._factory_settings()
        mock_exists.side_effect = _exists_stub()
        mock_generate_url.side_effect = _fake_print_url

        new_doc, created = _new_doc_recorder({"Label Record": "LBL-004"})
        mock_new_doc.side_effect = new_doc

        result = print_label(
            carton_qty=27,
            template="SATO FG Label Print",
            work_order="WO-001",
        )

        self.assertIsNone(created["Label Record"].batch_no)
        self.assertIsNone(created["Packed Carton"].batch_no)
        self.assertEqual(mock_generate_url.call_args.kwargs["batch_no"], "")
        self.assertIn("batch_no=&", result["print_url"])


def _label_record_doc(name="LBL-001", label_template="FG Pallet Label", quantity=1.0,
                      batch_no="BBB-111", payload=None,
                      source=("Work Order", "WO-001")):
    """A stored Label Record as print_label_record reads it back."""
    record = MagicMock()
    record.name = name
    record.label_template = label_template
    record.quantity = quantity
    record.batch_no = batch_no
    record.payload = payload
    row = MagicMock()
    row.source_doctype, row.source_docname = source
    record.sources = [row]
    return record


class TestPrintLabelRecordReprint(unittest.TestCase):
    """A reprint replays the stored batch and the original quantity, not the source doc's."""

    def _factory_settings(self):
        # No printer configured, so print_label_record creates no Print Jobs and
        # never reaches frappe.session / frappe.new_doc.
        fs = MagicMock()
        fs.enable_silent_printing = False
        fs.default_label_printer = None
        return fs

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.get_doc')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_pallet_reprint_renders_the_stored_carton_count_not_the_work_order_quantity(
            self, mock_generate_url, mock_fs, mock_get_doc, mock_exists, mock_require_roles):
        """A 27-carton pallet reprints at 27 cartons, not at the Work Order's full 300."""
        mock_exists.side_effect = _exists_stub()
        mock_fs.return_value = self._factory_settings()
        mock_generate_url.side_effect = _fake_print_url
        mock_get_doc.return_value = _label_record_doc(
            quantity=1.0,
            payload=json.dumps({
                "pallet_type": "EURO 1",
                "carton_qty": 27,
                "work_orders": ["WO-001"],
                "print_format": "FG Pallet Label",
            }),
        )

        result = print_label_record("LBL-001")

        self.assertEqual(len(result["print_urls"]), 1)
        url = result["print_urls"][0]
        self.assertIn("carton_qty=27", url)
        self.assertNotIn("carton_qty=300", url)
        self.assertIn("pallet_qty=1.0", url)
        self.assertIn("pallet_type=EURO%201", url)
        self.assertEqual(mock_generate_url.call_args.kwargs["carton_qty"], 27)

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.get_doc')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_multi_pallet_reprint_reproduces_the_original_split_not_the_run_total(
            self, mock_generate_url, mock_fs, mock_get_doc, mock_exists, mock_require_roles):
        """A pallet record is a SET of labels, so a reprint reproduces every one of them.

        The production case: 300 cartons over 3.296703297 pallets printed as
        91 + 91 + 91 + 27. Replaying the payload's stored carton_qty on a single
        label would put the whole run's 300 cartons on one pallet — and, because
        the FG format feeds carton_qty straight into the QR, a scan of that label
        would book 300 cartons against the Delivery Note.
        """
        mock_exists.side_effect = _exists_stub()
        mock_fs.return_value = self._factory_settings()
        mock_generate_url.side_effect = _fake_print_url
        mock_get_doc.return_value = _label_record_doc(
            quantity=3.296703297,
            payload=json.dumps({
                "pallet_type": "EUR 2 Pallet x 91",
                "carton_qty": 300.0,
                "work_orders": ["WO-001"],
            }),
        )

        result = print_label_record("LBL-001")

        cartons = [call.kwargs["carton_qty"] for call in mock_generate_url.call_args_list]
        self.assertEqual(cartons, [91, 91, 91, 27])
        self.assertEqual(sum(cartons), 300)
        self.assertEqual(len(result["print_urls"]), 4)
        for call in mock_generate_url.call_args_list:
            self.assertEqual(call.kwargs["batch_no"], "BBB-111")
            self.assertEqual(call.kwargs["pallet_type"], "EUR 2 Pallet x 91")

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.get_doc')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_pallet_split_reprint_shares_out_the_cartons_without_inventing_any(
            self, mock_generate_url, mock_fs, mock_get_doc, mock_exists, mock_require_roles):
        """Splitting the pallets splits their cartons too, and the shares sum back to the run."""
        mock_exists.side_effect = _exists_stub()
        mock_fs.return_value = self._factory_settings()
        mock_generate_url.side_effect = _fake_print_url
        mock_get_doc.return_value = _label_record_doc(
            quantity=3.296703297,
            payload=json.dumps({"pallet_type": "EUR 2 Pallet x 91", "carton_qty": 300.0}),
        )

        result = print_label_record("LBL-001", quantities='[2, 1.296703297]')

        cartons = [call.kwargs["carton_qty"] for call in mock_generate_url.call_args_list]
        self.assertEqual(sum(cartons), 300)
        self.assertEqual(cartons, [91, 91, 91, 27])
        self.assertEqual(len(result["print_urls"]), 4)

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.get_doc')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_pallet_reprint_carries_the_batch_stored_on_the_label_record(
            self, mock_generate_url, mock_fs, mock_get_doc, mock_exists, mock_require_roles):
        """The reprint labels the batch the original print recorded, not a re-resolved one."""
        mock_exists.side_effect = _exists_stub()
        mock_fs.return_value = self._factory_settings()
        mock_generate_url.side_effect = _fake_print_url
        mock_get_doc.return_value = _label_record_doc(
            quantity=1.0,
            payload=json.dumps({"pallet_type": "EURO 1", "carton_qty": 27}),
        )

        result = print_label_record("LBL-001")

        self.assertIn("batch_no=BBB-111", result["print_urls"][0])
        self.assertEqual(mock_generate_url.call_args.kwargs["batch_no"], "BBB-111")

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.get_doc')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_carton_reprint_sends_the_records_own_quantity_as_carton_qty(
            self, mock_generate_url, mock_fs, mock_get_doc, mock_exists, mock_require_roles):
        """A carton record stores "Print Format: X" rather than JSON, so the quantity comes off the record."""
        mock_exists.side_effect = _exists_stub()
        mock_fs.return_value = self._factory_settings()
        mock_generate_url.side_effect = _fake_print_url
        mock_get_doc.return_value = _label_record_doc(
            label_template="SATO FG Label Print",
            quantity=27.0,
            payload="Print Format: SATO FG Label Print",
        )

        result = print_label_record("LBL-001")

        self.assertEqual(len(result["print_urls"]), 1)
        self.assertIn("batch_no=BBB-111", result["print_urls"][0])
        self.assertEqual(mock_generate_url.call_args.kwargs["carton_qty"], 27.0)
        self.assertNotIn("pallet_qty", mock_generate_url.call_args.kwargs)

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.get_doc')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_split_reprint_gives_each_copy_its_own_quantity_and_the_stored_batch(
            self, mock_generate_url, mock_fs, mock_get_doc, mock_exists, mock_require_roles):
        """Splitting 27 cartons into 10 + 17 prints two different labels, both batch-stamped."""
        mock_exists.side_effect = _exists_stub()
        mock_fs.return_value = self._factory_settings()
        mock_generate_url.side_effect = _fake_print_url
        mock_get_doc.return_value = _label_record_doc(
            label_template="SATO FG Label Print",
            quantity=27.0,
            payload="Print Format: SATO FG Label Print",
        )

        result = print_label_record("LBL-001", quantities='[10, 17]')

        self.assertEqual(len(result["print_urls"]), 2)
        self.assertEqual(
            [call.kwargs["carton_qty"] for call in mock_generate_url.call_args_list],
            [10.0, 17.0],
        )
        self.assertEqual(
            [call.kwargs["batch_no"] for call in mock_generate_url.call_args_list],
            ["BBB-111", "BBB-111"],
        )
        self.assertEqual(len(set(result["print_urls"])), 2)

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.get_doc')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_stock_entry_reprint_leaves_every_row_to_resolve_its_own_batch(
            self, mock_generate_url, mock_fs, mock_get_doc, mock_exists, mock_require_roles):
        """The multi-item Stock Entry path sends no batch: the record's belongs to one row.

        Stamping the record-level batch on every row URL would relabel the other
        rows with it. Each row carries its own batch (directly or in its Serial
        and Batch Bundle) and the Stock Entry formats read it per row.
        """
        mock_exists.side_effect = _exists_stub()
        mock_fs.return_value = self._factory_settings()
        mock_generate_url.side_effect = _fake_print_url

        record = _label_record_doc(
            label_template="SATO Label Print",
            quantity=2.0,
            payload="Print Format: SATO Label Print",
            source=("Stock Entry", "STE-001"),
        )
        se_doc = MagicMock()
        rows = []
        for row_name, qty in (("row-a", 5), ("row-b", 7)):
            row = MagicMock()
            row.name = row_name
            row.qty = qty
            rows.append(row)
        se_doc.items = rows

        def get_doc_side_effect(doctype, docname=None):
            if doctype == "Label Record":
                return record
            if doctype == "Stock Entry":
                return se_doc
            return MagicMock()
        mock_get_doc.side_effect = get_doc_side_effect

        result = print_label_record("LBL-001")

        self.assertEqual(len(result["print_urls"]), 2)
        self.assertEqual(
            [call.kwargs["row_name"] for call in mock_generate_url.call_args_list],
            ["row-a", "row-b"],
        )
        for call in mock_generate_url.call_args_list:
            self.assertNotIn("batch_no", call.kwargs)
        for url in result["print_urls"]:
            self.assertNotIn("batch_no=", url)

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.get_doc')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    def test_reprint_of_a_pre_fix_record_resolves_the_batch_from_its_work_orders(
            self, mock_fg_batches, mock_generate_url, mock_fs, mock_get_doc, mock_exists,
            mock_require_roles):
        """A record stored before batches were stamped still reprints batch-stamped.

        All 38 Label Records that predate this change carry batch_no NULL, so the
        batch is read back from the Work Orders in the record's sources — the same
        lookup the original print would have done.
        """
        mock_exists.side_effect = _exists_stub()
        mock_fs.return_value = self._factory_settings()
        mock_generate_url.side_effect = _fake_print_url
        mock_fg_batches.return_value = "BBB-111"
        mock_get_doc.return_value = _label_record_doc(
            label_template="SATO FG Label Print",
            quantity=27.0,
            batch_no=None,
            payload="Print Format: SATO FG Label Print",
        )

        result = print_label_record("LBL-001")

        mock_fg_batches.assert_called_once_with(["WO-001"])
        self.assertIn("batch_no=BBB-111", result["print_urls"][0])
        self.assertEqual(mock_generate_url.call_args.kwargs["batch_no"], "BBB-111")

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists')
    @patch('frappe.get_doc')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    def test_reprint_sends_an_empty_batch_when_none_can_be_resolved(
            self, mock_fg_batches, mock_generate_url, mock_fs, mock_get_doc, mock_exists,
            mock_require_roles):
        """An unresolvable batch sends "" rather than the literal string "None"."""
        mock_exists.side_effect = _exists_stub()
        mock_fs.return_value = self._factory_settings()
        mock_generate_url.side_effect = _fake_print_url
        mock_fg_batches.return_value = None
        mock_get_doc.return_value = _label_record_doc(
            label_template="SATO FG Label Print",
            quantity=27.0,
            batch_no=None,
            payload="Print Format: SATO FG Label Print",
        )

        result = print_label_record("LBL-001")

        self.assertEqual(mock_generate_url.call_args.kwargs["batch_no"], "")
        self.assertIn("batch_no=&", result["print_urls"][0])
        self.assertNotIn("None", result["print_urls"][0])



class TestCombineLabelRecords(unittest.TestCase):
    """Combining pallet labels, and reprinting what the combine produced."""

    def _pallet_record(self, name, pallets, cartons, batch_no="BBB-111"):
        record = MagicMock()
        record.name = name
        record.quantity = pallets
        record.batch_no = batch_no
        record.item_code = "FG10011"
        record.item_name = "PUFFS - Super Cheesy 21pkt x 40g"
        record.label_template = "SATO FG Label Print"
        record.template_engine = "Jinja"
        record.payload = json.dumps({
            "pallet_type": "EUR 2 Pallet x 91",
            "carton_qty": cartons,
            "work_orders": ["WO-001"],
        })
        source = MagicMock()
        source.source_doctype, source.source_docname, source.name = "Work Order", "WO-001", "src-1"
        record.sources = [source]
        return record

    def _combine(self, records, **patches):
        """Run combine_label_records over `records`, returning (result, combined doc)."""
        created = {}

        def new_doc(doctype):
            doc = MagicMock()
            doc.name = "LBL-C"
            doc.sources = []
            doc.append = lambda field, value: doc.sources.append(MagicMock(**value))
            created["combined"] = doc
            return doc

        fs = MagicMock()
        fs.enable_silent_printing = False
        fs.default_label_printer = None

        with patch('isnack.api.mes_ops._require_roles'), \
                patch('isnack.api.mes_ops._fs', return_value=fs), \
                patch('isnack.api.mes_ops.fg_batch_for_work_orders',
                      return_value=patches.get("resolved_batch", "BBB-111")), \
                patch('frappe.db.exists', return_value=True), \
                patch('frappe.db.set_value'), \
                patch('frappe.get_doc', side_effect=lambda dt, n=None: records[n]), \
                patch('frappe.new_doc', side_effect=new_doc):
            result = combine_label_records(json.dumps(list(records)))
        return result, created["combined"]

    def _cartons(self, urls):
        out = []
        for url in urls:
            query = parse_qs(urlparse(url).query, keep_blank_values=True)
            out.append(query.get("carton_qty", [None])[0])
        return out

    def test_combined_pallet_label_keeps_the_cartons_each_pallet_carries(self):
        """A 273-carton record and a 27-carton one combine to 91,91,91,27 — not four 75s.

        The combined record's carton TOTAL says nothing about how the cartons sit
        on the pallets, and the FG format feeds carton_qty straight into the QR,
        so re-deriving the split from the total would book the wrong quantity on
        the Delivery Note when the label is scanned.
        """
        records = {
            "LBL-A": self._pallet_record("LBL-A", 3.0, 273.0),
            "LBL-B": self._pallet_record("LBL-B", 1.0, 27.0),
        }

        result, combined = self._combine(records)

        self.assertEqual(self._cartons(result["print_urls"]), ["91", "91", "91", "27"])
        payload = json.loads(combined.payload)
        self.assertEqual(payload["carton_splits"], [91, 91, 91, 27])
        self.assertEqual(payload["pallet_type"], "EUR 2 Pallet x 91")
        self.assertEqual(payload["carton_qty"], 300.0)

    def test_reprinting_a_combined_pallet_label_reproduces_it_exactly(self):
        """The regression: without pallet_type on the payload a reprint sent the PALLET count as carton_qty."""
        records = {
            "LBL-A": self._pallet_record("LBL-A", 3.0, 273.0),
            "LBL-B": self._pallet_record("LBL-B", 1.0, 27.0),
        }
        combine_result, combined = self._combine(records)

        fs = MagicMock()
        fs.enable_silent_printing = False
        fs.default_label_printer = None
        with patch('isnack.api.mes_ops._require_roles'), \
                patch('isnack.api.mes_ops._fs', return_value=fs), \
                patch('frappe.db.exists', return_value=True), \
                patch('frappe.get_doc', return_value=combined):
            reprint = print_label_record("LBL-C")

        self.assertEqual(self._cartons(reprint["print_urls"]), ["91", "91", "91", "27"])
        # the combined label and its reprint must be the same physical labels
        self.assertEqual(self._cartons(reprint["print_urls"]),
                         self._cartons(combine_result["print_urls"]))
        # and the pallet count must never be mistaken for a carton count
        self.assertNotIn("4.0", self._cartons(reprint["print_urls"]))

    def test_combined_label_carries_the_batch_on_every_url(self):
        records = {
            "LBL-A": self._pallet_record("LBL-A", 3.0, 273.0),
            "LBL-B": self._pallet_record("LBL-B", 1.0, 27.0),
        }

        result, combined = self._combine(records)

        self.assertEqual(combined.batch_no, "BBB-111")
        for url in result["print_urls"]:
            self.assertIn("batch_no=BBB-111", url)

    def test_a_pre_fix_label_combines_with_a_post_fix_one_for_the_same_batch(self):
        """Pre-fix records carry batch_no NULL; resolving before comparing keeps them combinable."""
        records = {
            "LBL-A": self._pallet_record("LBL-A", 3.0, 273.0, batch_no=None),
            "LBL-B": self._pallet_record("LBL-B", 1.0, 27.0, batch_no="BBB-111"),
        }

        result, combined = self._combine(records)

        self.assertEqual(combined.batch_no, "BBB-111")
        self.assertEqual(len(result["print_urls"]), 4)

    def test_labels_of_genuinely_different_batches_are_still_refused(self):
        """Resolving the batch must not weaken the check that stops a mixed-batch merge."""
        records = {
            "LBL-A": self._pallet_record("LBL-A", 3.0, 273.0, batch_no="BBB-111"),
            "LBL-B": self._pallet_record("LBL-B", 1.0, 27.0, batch_no="AAA-999"),
        }

        with self.assertRaises(frappe.ValidationError) as caught:
            self._combine(records)
        self.assertIn("same Batch", str(caught.exception))



# The client's real catalogue: every Finished Goods item is batch tracked, every
# Semi-Finished Goods item is not. Semi-finished output feeds the next Work
# Order and is never palletised or delivered, so it must not reach a label.
_ITEMS = {
    "FG10011": {"item_name": "PUFFS - Super Cheesy 21pkt x 40g", "description": "",
                "stock_uom": "Carton", "item_group": "Finished Goods"},
    "FG10006": {"item_name": "CRACKERS - Sea Salt 12pkt x 100g", "description": "",
                "stock_uom": "Carton", "item_group": "Finished Goods"},
    "SFG10001": {"item_name": "CORN MIX 1", "description": "",
                 "stock_uom": "Kg", "item_group": "Semi-Finished Goods"},
    "SFG10002": {"item_name": "PUFFS CHEESY SLURRY", "description": "",
                 "stock_uom": "Kg", "item_group": "Semi-Finished Goods"},
}


def _item_details(doctype, item_code, fields, as_dict=False):
    """frappe.db.get_value stand-in projecting _ITEMS to the fields asked for."""
    item = _ITEMS.get(item_code)
    if not item:
        return None
    return frappe._dict({f: item.get(f, "") for f in fields})


# ---------------------------------------------------------------------------
# One pallet-label row per (item, batch)
# ---------------------------------------------------------------------------

_TODAY = frappe.utils.today()
_YESTERDAY = (datetime.strptime(_TODAY, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")


def _wo_row(name, item_code, produced_qty, **kw):
    """A Work Order row as the pallet dialogs read it, closed today by default."""
    row = frappe._dict(
        name=name,
        production_item=item_code,
        produced_qty=produced_qty,
        status="Completed",
        actual_end_date=f"{_TODAY} 14:20:00",
        production_plan=None,
    )
    row.update(kw)
    return row


def _matches(row, filters):
    for field, condition in (filters or {}).items():
        value = row.get(field)
        if isinstance(condition, (list, tuple)):
            operator, operand = condition
            if operator == "in" and value not in operand:
                return False
            if operator == "between" and not (operand[0] <= str(value or "") <= operand[1]):
                return False
        elif value != condition:
            return False
    return True


def _table_reads(tables):
    """A ``frappe.get_all`` stand-in over in-memory tables that honours filters.

    The dialogs' "closed today", "status Completed" and "this Production Plan"
    rules are SQL. A canned return value would keep the tests passing if those
    filters were deleted, so the fixture is filtered here instead: a Work Order
    missing from a dialog was left out by the filter under test, not by the
    fake. Rows are projected to ``fields`` so a caller can only read what it
    actually asked the database for.
    """
    def get_all(doctype, filters=None, fields=None, **kwargs):
        return [
            frappe._dict({f: row.get(f) for f in (fields or row)})
            for row in tables.get(doctype, [])
            if _matches(row, filters)
        ]
    return get_all


class TestIsFgItemGroup(unittest.TestCase):
    """The Finished Good test, applied to a group already in hand."""

    def test_semi_finished_groups_are_not_finished_goods(self):
        for group in ("Semi-Finished Goods", "semi-finished goods", "  Semi-Finished  ",
                      "Line 2 Semi-Finished"):
            self.assertFalse(_is_fg_item_group(group), group)

    def test_everything_else_produced_is_a_finished_good(self):
        for group in ("Finished Goods", "Products", ""):
            self.assertTrue(_is_fg_item_group(group), group)

    def test_missing_group_is_not_treated_as_semi_finished(self):
        # Matches _is_fg: only an explicit "semi-finished" demotes an item.
        self.assertTrue(_is_fg_item_group(None))


class TestPalletLabelDataExcludesSemiFinished(unittest.TestCase):
    """The pallet dialogs say "FG only" — the data behind them has to mean it."""

    def _factory_settings(self):
        fs = MagicMock()
        fs.pallet_uom_options = []
        return fs

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_closed_semi_finished_work_orders_are_left_out(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles):
        """A day that closed one FG and two SFG Work Orders lists only the FG.

        Taken from the customer's 2026-09-14: FG10011 alongside CORN MIX 1 and
        PUFFS CHEESY SLURRY, which is what put semi-finished rows in the dialog.
        The dialog now lists one row per (item, batch), so the finished good
        arrives as an (item, batch) pair rather than as a bare item.
        """
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00061", "FG10011", 300),
            _wo_row("MFG-WO-2026-00062", "SFG10001", 160),
            _wo_row("MFG-WO-2026-00063", "SFG10002", 120),
        ]})
        mock_quantities.return_value = {"MFG-WO-2026-00061": [("MJB-079", 300.0)]}

        out = get_pallet_label_data()

        self.assertEqual([(i["item_code"], i["batch_no"]) for i in out["items"]],
                         [("FG10011", "MJB-079")])
        self.assertEqual(out["items"][0]["carton_qty"], 300)
        # the batch resolver reads Stock Entries: it must not be asked about the
        # semi-finished Work Orders the dialog is about to throw away
        self.assertEqual(mock_quantities.call_args.args[0], ["MFG-WO-2026-00061"])

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_a_day_of_only_semi_finished_work_orders_lists_nothing(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles):
        """The customer's 2026-08-06 closed semi-finished only; the dialog must come up empty.

        Not even a batch-less row: the fallback row exists for finished goods
        whose batch could not be read, not for output that is never palletised.
        """
        mock_cached_doc.return_value = self._factory_settings()
        mock_quantities.return_value = {}
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00055", "SFG10002", 80),
        ]})

        self.assertEqual(get_pallet_label_data()["items"], [])

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops._pallet_label_print_summary')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_production_plan_dialog_excludes_its_semi_finished_stages(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_summary, mock_require_roles):
        """A Production Plan's Work Orders include the stages that feed the finished ones."""
        mock_cached_doc.return_value = self._factory_settings()
        mock_summary.return_value = {"printed_wo_count": 0, "label_count": 0, "last_printed_on": None}
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00061", "FG10011", 300, production_plan="MFG-PP-2026-00036"),
            _wo_row("MFG-WO-2026-00062", "SFG10001", 160, production_plan="MFG-PP-2026-00036"),
        ]})
        mock_quantities.return_value = {"MFG-WO-2026-00061": [("MJB-079", 300.0)]}

        out = get_pallet_label_data_for_production_plan("MFG-PP-2026-00036")

        self.assertEqual([(i["item_code"], i["batch_no"]) for i in out["items"]],
                         [("FG10011", "MJB-079")])
        # the summary is the expensive read: one call per surviving row, and
        # none at all for an excluded item
        self.assertEqual(mock_summary.call_count, 1)


class TestPrintPalletLabelRefusesSemiFinished(unittest.TestCase):
    """Hiding the row is not enough: print_pallet_label is whitelisted."""

    def _work_order_rows(self, *pairs):
        def get_all(doctype, **kwargs):
            if doctype == "Work Order":
                return [frappe._dict(production_item=item) for _, item in pairs]
            if doctype == "Item":
                return [frappe._dict(name=i, item_group=_ITEMS[i]["item_group"])
                        for i in sorted({item for _, item in pairs})]
            return []
        return get_all

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists', return_value=True)
    @patch('frappe.get_all')
    def test_a_semi_finished_work_order_is_refused(
            self, mock_get_all, mock_exists, mock_require_roles):
        mock_get_all.side_effect = self._work_order_rows(("WO-002", "SFG10002"))

        with self.assertRaises(frappe.ValidationError) as caught:
            print_pallet_label(
                item_code="SFG10002", pallet_qty=1.0, pallet_type="EURO 1",
                work_orders='["WO-002"]', template="SATO FG Label Print",
            )
        message = str(caught.exception)
        self.assertIn("SFG10002", message)
        self.assertIn("finished goods", message)

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists', return_value=True)
    @patch('frappe.get_all')
    def test_one_semi_finished_work_order_refuses_the_whole_pallet(
            self, mock_get_all, mock_exists, mock_require_roles):
        """A pallet spanning Work Orders is refused if any of them is semi-finished."""
        mock_get_all.side_effect = self._work_order_rows(
            ("WO-001", "FG10011"), ("WO-002", "SFG10001"))

        with self.assertRaises(frappe.ValidationError) as caught:
            print_pallet_label(
                item_code="FG10011", pallet_qty=1.0, pallet_type="EURO 1",
                work_orders='["WO-001", "WO-002"]', template="SATO FG Label Print",
            )
        self.assertIn("SFG10001", str(caught.exception))

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.db.exists', return_value=True)
    @patch('frappe.get_all')
    def test_a_finished_good_is_not_refused(
            self, mock_get_all, mock_exists, mock_require_roles):
        """The guard must not fire for the labels the dialog exists to print."""
        mock_get_all.side_effect = self._work_order_rows(("WO-001", "FG10011"))

        # Past the guard the call needs the rest of its collaborators; getting a
        # different failure than the guard's is what proves the guard let it by.
        with self.assertRaises(Exception) as caught:
            print_pallet_label(
                item_code="FG10011", pallet_qty=1.0, pallet_type="EURO 1",
                work_orders='["WO-001"]', template=None,
            )
        self.assertNotIn("semi-finished", str(caught.exception))


class _PalletDialogTestCase(unittest.TestCase):
    """Shared scaffolding for the two pallet-label dialogs."""

    def _factory_settings(self):
        fs = MagicMock()
        fs.pallet_uom_options = []
        return fs

    def _rows(self, items):
        """(item_code, batch_no, carton_qty, work_orders) for each dialog row."""
        return [(i["item_code"], i["batch_no"], i["carton_qty"], i["work_orders"]) for i in items]


class TestPalletLabelRowsPerBatch(_PalletDialogTestCase):
    """The Operator Hub dialog lists one row per (item, batch), not per item.

    One row per item aggregated every Work Order closed that day, so when those
    Work Orders had booked different batches the row spanned two of them.
    print_pallet_label then resolved to no batch on purpose — one label cannot
    carry two — and the label printed "Batch -" with a QR of ITEM||QTY. The
    Delivery Note scanner refuses a batch-less label for a batch-tracked item,
    which is how label LBL-2026-09-00737 became a dead end. Splitting the rows
    by batch means every print call spans exactly one batch.
    """

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_an_item_produced_in_two_batches_today_gets_a_row_for_each_batch(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles):
        """The customer's reported case: two Work Orders, one item, two batches.

        Each row carries its own batch, its own carton count and only the Work
        Orders that produced it — the two 770/600 totals stay apart instead of
        becoming one unprintable 1370.
        """
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00071", "FG10011", 600),
            _wo_row("MFG-WO-2026-00072", "FG10011", 770),
        ]})
        mock_quantities.return_value = {
            "MFG-WO-2026-00071": [("MJB-079", 600.0)],
            "MFG-WO-2026-00072": [("BBJ-504", 770.0)],
        }

        rows = self._rows(get_pallet_label_data()["items"])

        self.assertEqual(rows, [
            ("FG10011", "MJB-079", 600.0, ["MFG-WO-2026-00071"]),
            ("FG10011", "BBJ-504", 770.0, ["MFG-WO-2026-00072"]),
        ])

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_an_item_produced_in_one_batch_still_gets_exactly_one_row(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles):
        """The common case: splitting by batch must not split the ordinary day."""
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00061", "FG10011", 300),
        ]})
        mock_quantities.return_value = {"MFG-WO-2026-00061": [("MJB-079", 300.0)]}

        rows = self._rows(get_pallet_label_data()["items"])

        self.assertEqual(rows, [("FG10011", "MJB-079", 300.0, ["MFG-WO-2026-00061"])])

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_work_orders_that_booked_the_same_batch_stay_on_one_row(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles):
        """Splitting is by batch, not by Work Order: a batch filled by two Work
        Orders is still one pallet run and still one row."""
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00061", "FG10011", 100),
            _wo_row("MFG-WO-2026-00062", "FG10011", 120),
        ]})
        mock_quantities.return_value = {
            "MFG-WO-2026-00061": [("MJB-079", 100.0)],
            "MFG-WO-2026-00062": [("MJB-079", 120.0)],
        }

        rows = self._rows(get_pallet_label_data()["items"])

        self.assertEqual(rows, [
            ("FG10011", "MJB-079", 220.0, ["MFG-WO-2026-00061", "MFG-WO-2026-00062"]),
        ])

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_a_work_order_whose_batch_cannot_be_read_keeps_its_cartons_in_a_batchless_row(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles):
        """Nothing produced may vanish from the dialog.

        Cartons that were made and are not on the screen would be a worse
        failure than the blank batch this split exists to prevent, so a Work
        Order the resolver cannot place keeps its produced_qty in a row of its
        own with no batch.
        """
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00061", "FG10011", 300),
            _wo_row("MFG-WO-2026-00062", "FG10011", 50),
        ]})
        # the second Work Order is simply absent from the resolver's map
        mock_quantities.return_value = {"MFG-WO-2026-00061": [("MJB-079", 300.0)]}

        rows = self._rows(get_pallet_label_data()["items"])

        self.assertEqual(rows, [
            ("FG10011", "MJB-079", 300.0, ["MFG-WO-2026-00061"]),
            ("FG10011", None, 50.0, ["MFG-WO-2026-00062"]),
        ])

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_a_work_order_that_produced_two_batches_appears_in_both_rows(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles):
        """One Work Order, one produced_qty, two batches: each row lists the Work
        Order and carries only that batch's share of its output."""
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00071", "FG10011", 220),
        ]})
        mock_quantities.return_value = {
            "MFG-WO-2026-00071": [("MJB-079", 120.0), ("BBJ-504", 100.0)],
        }

        rows = self._rows(get_pallet_label_data()["items"])

        self.assertEqual(rows, [
            ("FG10011", "MJB-079", 120.0, ["MFG-WO-2026-00071"]),
            ("FG10011", "BBJ-504", 100.0, ["MFG-WO-2026-00071"]),
        ])
        self.assertEqual(sum(r[2] for r in rows), 220.0)

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_rows_are_ordered_by_item_then_by_batch_in_first_seen_order(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles):
        """Items alphabetically, and within an item the batches in the order the
        day ran — including the batch-less row, which is production too."""
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            # read back creation-ascending, which is the order production ran
            _wo_row("MFG-WO-2026-00061", "FG10011", 300),
            _wo_row("MFG-WO-2026-00062", "FG10006", 100),
            _wo_row("MFG-WO-2026-00063", "FG10011", 50),
            _wo_row("MFG-WO-2026-00064", "FG10011", 70),
        ]})
        mock_quantities.return_value = {
            "MFG-WO-2026-00061": [("MJB-079", 300.0)],
            "MFG-WO-2026-00062": [("CRK-012", 100.0)],
            # 00063 resolves to nothing, so FG10011's middle row has no batch
            "MFG-WO-2026-00064": [("BBJ-504", 70.0)],
        }

        rows = self._rows(get_pallet_label_data()["items"])

        self.assertEqual([(r[0], r[1]) for r in rows], [
            ("FG10006", "CRK-012"),
            ("FG10011", "MJB-079"),
            ("FG10011", None),
            ("FG10011", "BBJ-504"),
        ])

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_every_batch_row_still_carries_the_item_fields_the_grid_renders(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles):
        """Splitting a row must not cost it the columns the dialog draws."""
        fs = self._factory_settings()
        fs.pallet_uom_options = [frappe._dict(uom="EURO 1"), frappe._dict(uom="EURO 4")]
        mock_cached_doc.return_value = fs
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00071", "FG10011", 220),
        ]})
        mock_quantities.return_value = {
            "MFG-WO-2026-00071": [("MJB-079", 120.0), ("BBJ-504", 100.0)],
        }

        out = get_pallet_label_data()

        for row in out["items"]:
            self.assertEqual(row["item_name"], "PUFFS - Super Cheesy 21pkt x 40g")
            self.assertEqual(row["default_uom"], "Carton")
            self.assertIn("description", row)
        self.assertEqual(out["allowed_pallet_uoms"], ["EURO 1", "EURO 4"])


class TestPalletLabelDataStillFiltersTheDay(_PalletDialogTestCase):
    """The split changed which rows the day makes, not which Work Orders it reads."""

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_a_work_order_closed_on_an_earlier_day_is_still_left_out(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles):
        """Yesterday's batch must not reappear as an extra row today."""
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00061", "FG10011", 300),
            _wo_row("MFG-WO-2026-00055", "FG10011", 180,
                    actual_end_date=f"{_YESTERDAY} 17:40:00"),
        ]})
        mock_quantities.return_value = {
            "MFG-WO-2026-00061": [("MJB-079", 300.0)],
            "MFG-WO-2026-00055": [("BBJ-504", 180.0)],
        }

        rows = self._rows(get_pallet_label_data()["items"])

        self.assertEqual(rows, [("FG10011", "MJB-079", 300.0, ["MFG-WO-2026-00061"])])

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_a_work_order_that_is_not_completed_is_still_left_out(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles):
        """Production still running has no final batch quantity to label."""
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00061", "FG10011", 300),
            _wo_row("MFG-WO-2026-00064", "FG10011", 40, status="In Process"),
        ]})
        mock_quantities.return_value = {
            "MFG-WO-2026-00061": [("MJB-079", 300.0)],
            "MFG-WO-2026-00064": [("BBJ-504", 40.0)],
        }

        rows = self._rows(get_pallet_label_data()["items"])

        self.assertEqual(rows, [("FG10011", "MJB-079", 300.0, ["MFG-WO-2026-00061"])])

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_the_day_is_still_read_as_a_full_day_range_on_actual_end_date(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles):
        """Pinned at the query, because a label closed at 23:50 is still today's."""
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = _table_reads({"Work Order": []})
        mock_quantities.return_value = {}

        get_pallet_label_data()

        filters = mock_get_all.call_args.kwargs["filters"]
        self.assertEqual(filters["status"], "Completed")
        self.assertEqual(
            filters["actual_end_date"],
            ["between", [f"{_TODAY} 00:00:00", f"{_TODAY} 23:59:59"]],
        )

    @patch('isnack.api.mes_ops._line_for_work_order')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_another_lines_batches_are_still_left_out(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_require_roles, mock_line):
        """Selecting a line still scopes the dialog, now per batch row."""
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00061", "FG10011", 300, custom_factory_line="Line 1"),
            _wo_row("MFG-WO-2026-00062", "FG10011", 180, custom_factory_line="Line 2"),
        ]})
        mock_line.side_effect = lambda name: {
            "MFG-WO-2026-00061": "Line 1", "MFG-WO-2026-00062": "Line 2"}[name]
        mock_quantities.return_value = {
            "MFG-WO-2026-00061": [("MJB-079", 300.0)],
            "MFG-WO-2026-00062": [("BBJ-504", 180.0)],
        }

        rows = self._rows(get_pallet_label_data(lines=json.dumps(["Line 1"]))["items"])

        self.assertEqual(rows, [("FG10011", "MJB-079", 300.0, ["MFG-WO-2026-00061"])])


class TestProductionPlanPalletLabelRowsPerBatch(_PalletDialogTestCase):
    """The Production Plan reprint dialog gets the same split, plus its own
    printed-status fields computed for each (item, batch) row."""

    _PLAN = "MFG-PP-2026-00036"

    def _summary(self, printed_wo_count=0, label_count=0, last_printed_on=None):
        return {"printed_wo_count": printed_wo_count, "label_count": label_count,
                "last_printed_on": last_printed_on}

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops._pallet_label_print_summary')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_a_plans_item_produced_in_two_batches_gets_a_row_for_each_batch(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_summary, mock_require_roles):
        mock_cached_doc.return_value = self._factory_settings()
        mock_summary.return_value = self._summary()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00071", "FG10011", 600, production_plan=self._PLAN),
            _wo_row("MFG-WO-2026-00072", "FG10011", 770, production_plan=self._PLAN),
        ]})
        mock_quantities.return_value = {
            "MFG-WO-2026-00071": [("MJB-079", 600.0)],
            "MFG-WO-2026-00072": [("BBJ-504", 770.0)],
        }

        rows = self._rows(get_pallet_label_data_for_production_plan(self._PLAN)["items"])

        self.assertEqual(rows, [
            ("FG10011", "MJB-079", 600.0, ["MFG-WO-2026-00071"]),
            ("FG10011", "BBJ-504", 770.0, ["MFG-WO-2026-00072"]),
        ])

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops._pallet_label_print_summary')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_each_batch_row_reports_the_printed_status_of_its_own_work_orders(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_summary, mock_require_roles):
        """The summary is computed per row, off that row's Work Orders, so the
        two batches of one item can read differently."""
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00071", "FG10011", 600, production_plan=self._PLAN),
            _wo_row("MFG-WO-2026-00072", "FG10011", 770, production_plan=self._PLAN),
        ]})
        mock_quantities.return_value = {
            "MFG-WO-2026-00071": [("MJB-079", 600.0)],
            "MFG-WO-2026-00072": [("BBJ-504", 770.0)],
        }
        mock_summary.side_effect = lambda wos, batch=None: (
            self._summary(1, 2, "2026-09-15 09:12:00") if wos == ["MFG-WO-2026-00071"]
            else self._summary()
        )

        items = get_pallet_label_data_for_production_plan(self._PLAN)["items"]

        # The batch goes with the Work Orders: a Work Order that booked two
        # batches appears in both rows, so counting by Work Order alone would
        # make printing one batch mark the other batch's row as printed.
        self.assertEqual(
            [(c.args[0], c.args[1]) for c in mock_summary.call_args_list],
            [(["MFG-WO-2026-00071"], "MJB-079"), (["MFG-WO-2026-00072"], "BBJ-504")],
        )
        self.assertEqual([i["printed_wo_count"] for i in items], [1, 0])
        self.assertEqual([i["label_count"] for i in items], [2, 0])
        self.assertEqual([i["total_wo_count"] for i in items], [1, 1])
        self.assertEqual([i["last_printed_on"] for i in items], ["2026-09-15 09:12:00", None])

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops._pallet_label_print_summary')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_a_plans_work_order_with_no_readable_batch_keeps_its_own_row(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_summary, mock_require_roles):
        mock_cached_doc.return_value = self._factory_settings()
        mock_summary.return_value = self._summary()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00061", "FG10011", 300, production_plan=self._PLAN),
            _wo_row("MFG-WO-2026-00062", "FG10011", 50, production_plan=self._PLAN),
        ]})
        mock_quantities.return_value = {"MFG-WO-2026-00061": [("MJB-079", 300.0)]}

        rows = self._rows(get_pallet_label_data_for_production_plan(self._PLAN)["items"])

        self.assertEqual(rows, [
            ("FG10011", "MJB-079", 300.0, ["MFG-WO-2026-00061"]),
            ("FG10011", None, 50.0, ["MFG-WO-2026-00062"]),
        ])

    @patch('isnack.api.mes_ops._require_roles')
    @patch('isnack.api.mes_ops._pallet_label_print_summary')
    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_another_plans_work_orders_are_still_left_out(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_quantities,
            mock_summary, mock_require_roles):
        mock_cached_doc.return_value = self._factory_settings()
        mock_summary.return_value = self._summary()
        mock_get_all.side_effect = _table_reads({"Work Order": [
            _wo_row("MFG-WO-2026-00061", "FG10011", 300, production_plan=self._PLAN),
            _wo_row("MFG-WO-2026-00099", "FG10011", 90, production_plan="MFG-PP-2026-00041"),
            _wo_row("MFG-WO-2026-00098", "FG10011", 90, production_plan=self._PLAN,
                    status="In Process"),
        ]})
        mock_quantities.return_value = {
            "MFG-WO-2026-00061": [("MJB-079", 300.0)],
            "MFG-WO-2026-00099": [("BBJ-504", 90.0)],
            "MFG-WO-2026-00098": [("CRK-012", 90.0)],
        }

        rows = self._rows(get_pallet_label_data_for_production_plan(self._PLAN)["items"])

        self.assertEqual(rows, [("FG10011", "MJB-079", 300.0, ["MFG-WO-2026-00061"])])


class TestPrintPalletLabelSuppliedBatch(unittest.TestCase):
    """print_pallet_label takes the batch the dialog row already resolved.

    A per-batch row knows its batch, so the print call no longer has to
    re-derive it from a Work Order that may have booked two. The batch is still
    checked against what those Work Orders really produced: it ends up on the
    label's QR code, which is what a Delivery Note scan books stock against, so
    a client bug must not be able to stamp an arbitrary batch onto stock.
    """

    # WO-001 closed two batches; WO-002 closed only the second
    PRODUCED = {
        "WO-001": [("MJB-079", 120.0), ("BBJ-504", 100.0)],
        "WO-002": [("BBJ-504", 90.0)],
    }

    def _produced(self, work_orders):
        """The resolver's answer, restricted to the Work Orders it was asked about."""
        return {wo: self.PRODUCED[wo] for wo in work_orders if wo in self.PRODUCED}

    def _factory_settings(self):
        fs = MagicMock()
        fs.default_fg_label_print_format = "FG Pallet Label"
        fs.enable_silent_printing = False
        fs.default_label_printer = None
        return fs

    def _work_order_items(self, doctype, **kwargs):
        """The finished-goods guard's own two reads; everything else is mocked."""
        if doctype == "Work Order":
            return [frappe._dict(production_item="FG10011")]
        if doctype == "Item":
            return [frappe._dict(name="FG10011", item_group="Finished Goods")]
        return []

    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_all')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('frappe.new_doc')
    def test_a_supplied_batch_is_stamped_on_the_label_record_and_on_every_url(
            self, mock_new_doc, mock_generate_url, mock_fs, mock_get_value, mock_exists,
            mock_get_all, mock_require_roles, mock_legacy, mock_quantities):
        """Printing the BBJ-504 row of a Work Order that also made MJB-079."""
        mock_fs.return_value = self._factory_settings()
        mock_exists.side_effect = _exists_stub()
        mock_get_all.side_effect = self._work_order_items
        mock_get_value.return_value = {"item_name": "Test Item"}
        mock_generate_url.side_effect = _fake_print_url
        mock_quantities.side_effect = self._produced

        new_doc, created = _new_doc_recorder({"Label Record": "LBL-001"})
        mock_new_doc.side_effect = new_doc

        result = print_pallet_label(
            item_code="FG10011",
            pallet_qty=2.0,
            pallet_type="EURO 1",
            work_orders='["WO-001"]',
            template="FG Pallet Label",
            carton_qty=100,
            batch_no="BBJ-504",
        )

        self.assertEqual(created["Label Record"].batch_no, "BBJ-504")
        self.assertEqual(
            [call.kwargs["batch_no"] for call in mock_generate_url.call_args_list],
            ["BBJ-504", "BBJ-504"],
        )
        for url in result["print_urls"]:
            self.assertIn("batch_no=BBJ-504", url)

    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_all')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_a_supplied_batch_is_used_instead_of_re_resolving_from_the_work_orders(
            self, mock_generate_url, mock_fs, mock_get_value, mock_exists,
            mock_get_all, mock_require_roles, mock_legacy, mock_quantities):
        """The old resolver would answer None here — the Work Order booked two
        batches — which is exactly the blank label this change removes."""
        mock_fs.return_value = self._factory_settings()
        mock_exists.side_effect = _exists_stub(())
        mock_get_all.side_effect = self._work_order_items
        mock_get_value.return_value = {"item_name": "Test Item"}
        mock_generate_url.side_effect = _fake_print_url
        mock_quantities.side_effect = self._produced
        mock_legacy.return_value = None

        result = print_pallet_label(
            item_code="FG10011", pallet_qty=1.0, pallet_type="EURO 1",
            work_orders='["WO-001"]', template="FG Pallet Label", carton_qty=120,
            batch_no="MJB-079",
        )

        mock_legacy.assert_not_called()
        self.assertIn("batch_no=MJB-079", result["print_url"])

    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_all')
    @patch('frappe.db.exists')
    def test_a_batch_the_work_orders_did_not_produce_is_refused(
            self, mock_exists, mock_get_all, mock_require_roles, mock_quantities):
        """Refused before anything is written, and the message names both the
        batch and the Work Orders so the bad call can be traced."""
        mock_exists.side_effect = _exists_stub()
        mock_get_all.side_effect = self._work_order_items
        mock_quantities.side_effect = self._produced

        with self.assertRaises(frappe.ValidationError) as caught:
            print_pallet_label(
                item_code="FG10011", pallet_qty=1.0, pallet_type="EURO 1",
                work_orders='["WO-002"]', template="FG Pallet Label", carton_qty=90,
                batch_no="MJB-079",
            )

        message = str(caught.exception)
        self.assertIn("MJB-079", message)
        self.assertIn("WO-002", message)

    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_all')
    @patch('frappe.db.exists')
    @patch('frappe.new_doc')
    def test_a_refused_batch_never_reaches_a_label_record(
            self, mock_new_doc, mock_exists, mock_get_all, mock_require_roles,
            mock_quantities):
        """The check runs before the Label Record is created, so a rejected
        print leaves no audit trail claiming it happened."""
        mock_exists.side_effect = _exists_stub()
        mock_get_all.side_effect = self._work_order_items
        mock_quantities.side_effect = self._produced

        with self.assertRaises(frappe.ValidationError):
            print_pallet_label(
                item_code="FG10011", pallet_qty=1.0, pallet_type="EURO 1",
                work_orders='["WO-001"]', template="FG Pallet Label", carton_qty=100,
                batch_no="LBL-2026-09-00737",
            )

        mock_new_doc.assert_not_called()

    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_all')
    @patch('frappe.db.exists')
    def test_a_batch_that_could_not_be_read_at_all_says_so_instead_of_blaming_the_caller(
            self, mock_exists, mock_get_all, mock_require_roles, mock_quantities):
        """The resolver swallows read failures and answers with an empty map. A
        database that is down must not be reported as a wrong batch."""
        mock_exists.side_effect = _exists_stub()
        mock_get_all.side_effect = self._work_order_items
        mock_quantities.return_value = {}

        with self.assertRaises(frappe.ValidationError) as caught:
            print_pallet_label(
                item_code="FG10011", pallet_qty=1.0, pallet_type="EURO 1",
                work_orders='["WO-001"]', template="FG Pallet Label", carton_qty=100,
                batch_no="MJB-079",
            )

        message = str(caught.exception)
        self.assertIn("could be read", message)
        self.assertNotIn("was not produced", message)

    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_all')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    def test_a_batch_any_of_the_pallets_work_orders_produced_is_accepted(
            self, mock_generate_url, mock_fs, mock_get_value, mock_exists,
            mock_get_all, mock_require_roles, mock_legacy, mock_quantities):
        """A per-batch row may list several Work Orders, and they all put stock
        into that one batch, so the check is against what the pallet produced
        between them."""
        mock_fs.return_value = self._factory_settings()
        mock_exists.side_effect = _exists_stub(())
        mock_get_all.side_effect = self._work_order_items
        mock_get_value.return_value = {"item_name": "Test Item"}
        mock_generate_url.side_effect = _fake_print_url
        mock_quantities.side_effect = self._produced

        result = print_pallet_label(
            item_code="FG10011", pallet_qty=1.0, pallet_type="EURO 1",
            work_orders='["WO-001", "WO-002"]', template="FG Pallet Label", carton_qty=190,
            batch_no="BBJ-504",
        )

        self.assertIn("batch_no=BBJ-504", result["print_url"])

    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_all')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('frappe.new_doc')
    def test_no_batch_argument_still_resolves_the_batch_from_the_work_orders(
            self, mock_new_doc, mock_generate_url, mock_fs, mock_get_value, mock_exists,
            mock_get_all, mock_require_roles, mock_legacy, mock_quantities):
        """Every caller that predates the per-batch rows behaves as it did."""
        mock_fs.return_value = self._factory_settings()
        mock_exists.side_effect = _exists_stub()
        mock_get_all.side_effect = self._work_order_items
        mock_get_value.return_value = {"item_name": "Test Item"}
        mock_generate_url.side_effect = _fake_print_url
        mock_legacy.return_value = "BBJ-504"

        new_doc, created = _new_doc_recorder({"Label Record": "LBL-003"})
        mock_new_doc.side_effect = new_doc

        result = print_pallet_label(
            item_code="FG10011", pallet_qty=1.0, pallet_type="EURO 1",
            work_orders='["WO-002"]', template="FG Pallet Label", carton_qty=90,
        )

        mock_legacy.assert_called_once_with(["WO-002"])
        mock_quantities.assert_not_called()
        self.assertEqual(created["Label Record"].batch_no, "BBJ-504")
        self.assertIn("batch_no=BBJ-504", result["print_url"])

    @patch('isnack.api.mes_ops.fg_batch_quantities_by_work_order')
    @patch('isnack.api.mes_ops.fg_batch_for_work_orders')
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_all')
    @patch('frappe.db.exists')
    @patch('frappe.db.get_value')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('frappe.new_doc')
    def test_an_empty_batch_argument_is_read_as_no_batch_supplied(
            self, mock_new_doc, mock_generate_url, mock_fs, mock_get_value, mock_exists,
            mock_get_all, mock_require_roles, mock_legacy, mock_quantities):
        """An empty argument means "this row has no batch", not "resolve one".

        It is the one row the split exists to keep on screen, so it stays
        printable — but printable WITHOUT a batch. Only an omitted argument
        (the legacy callers) asks the server to resolve one from the Work
        Orders; treating empty the same way would stamp a batch on the very
        row the dialog showed as having none.
        """
        mock_fs.return_value = self._factory_settings()
        mock_exists.side_effect = _exists_stub()
        mock_get_all.side_effect = self._work_order_items
        mock_get_value.return_value = {"item_name": "Test Item"}
        mock_generate_url.side_effect = _fake_print_url
        mock_legacy.return_value = None

        for supplied in ("", "   ", None):
            with self.subTest(batch_no=supplied):
                mock_legacy.reset_mock()
                new_doc, created = _new_doc_recorder({"Label Record": "LBL-004"})
                mock_new_doc.side_effect = new_doc

                result = print_pallet_label(
                    item_code="FG10011", pallet_qty=1.0, pallet_type="EURO 1",
                    work_orders='["WO-003"]', template="FG Pallet Label", carton_qty=50,
                    batch_no=supplied,
                )

                if supplied is None:
                    # omitted: the legacy callers still ask the server to resolve
                    mock_legacy.assert_called_once_with(["WO-003"])
                else:
                    # supplied but empty: the row says it has no batch, and the
                    # server must take its word rather than resolving one
                    mock_legacy.assert_not_called()
                self.assertIsNone(created["Label Record"].batch_no)
                self.assertIn("batch_no=&", result["print_url"])


class TestBatchlessRowKeepsItsBatchOff(unittest.TestCase):
    """A row the dialog drew with no batch must not print one.

    This is the end-to-end shape of the fix, with the real resolver behind it:
    the row builder and the print call have to agree about which cartons belong
    to which batch, because the batch on the label is what a Delivery Note scan
    books stock against.
    """

    def _factory_settings(self):
        fs = MagicMock()
        fs.pallet_uom_options = []
        fs.default_fg_label_print_format = "FG Pallet Label"
        fs.enable_silent_printing = False
        fs.default_label_printer = None
        return fs

    def _reads(self):
        """WO-001 produced 220 cartons: 120 into MJB-079 and 100 with no batch.

        The unbatched 100 is a finished row the resolver cannot place — a
        Manufacture entry posted by hand, or a finished row whose batch was
        never written. Whatever put it there, those cartons are not in MJB-079.
        """
        return _table_reads({
            "Work Order": [_wo_row("WO-001", "FG10011", 220)],
            "Item": [frappe._dict(name="FG10011", item_group="Finished Goods")],
            "Stock Entry": [frappe._dict(
                name="SE-1", work_order="WO-001", purpose="Manufacture", docstatus=1,
                posting_date=_TODAY, posting_time="14:20:00")],
            "Stock Entry Detail": [
                frappe._dict(parent="SE-1", parenttype="Stock Entry", idx=1,
                             is_finished_item=1, is_scrap_item=0, batch_no="MJB-079",
                             serial_and_batch_bundle=None, transfer_qty=120, qty=120),
                frappe._dict(parent="SE-1", parenttype="Stock Entry", idx=2,
                             is_finished_item=1, is_scrap_item=0, batch_no=None,
                             serial_and_batch_bundle=None, transfer_qty=100, qty=100),
            ],
        })

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.get_all')
    def test_the_unplaceable_cartons_are_shown_in_a_row_of_their_own(
            self, mock_get_all, mock_get_value, mock_cached_doc, mock_require_roles):
        mock_cached_doc.return_value = self._factory_settings()
        mock_get_all.side_effect = self._reads()

        items = get_pallet_label_data()["items"]

        self.assertEqual(
            [(i["batch_no"], i["carton_qty"]) for i in items],
            [("MJB-079", 120.0), (None, 100.0)],
        )

    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_cached_doc')
    @patch('frappe.db.get_value', side_effect=_item_details)
    @patch('frappe.db.exists')
    @patch('isnack.api.mes_ops._fs')
    @patch('isnack.api.mes_ops._generate_print_url')
    @patch('frappe.new_doc')
    @patch('frappe.get_all')
    def test_printing_the_batchless_row_does_not_stamp_the_work_orders_other_batch(
            self, mock_get_all, mock_new_doc, mock_generate_url, mock_fs, mock_exists,
            mock_get_value, mock_cached_doc, mock_require_roles):
        """The dialog showed these 100 cartons with no batch; the label must agree.

        The client sends an EMPTY batch for a batch-less row, which is not the
        same as omitting the argument: omitted asks the server to resolve, and
        WO-001 has exactly one readable batch, MJB-079. Resolving here would put
        100 cartons that are not in MJB-079 onto a label whose QR books them
        into it — worse than the blank batch the split set out to remove.
        """
        mock_cached_doc.return_value = self._factory_settings()
        mock_fs.return_value = self._factory_settings()
        mock_exists.side_effect = _exists_stub()
        mock_generate_url.side_effect = _fake_print_url
        mock_get_all.side_effect = self._reads()

        batchless = [i for i in get_pallet_label_data()["items"] if i["batch_no"] is None][0]

        new_doc, created = _new_doc_recorder({"Label Record": "LBL-005"})
        mock_new_doc.side_effect = new_doc

        result = print_pallet_label(
            item_code=batchless["item_code"],
            pallet_qty=1.0,
            pallet_type="EURO 1",
            work_orders=json.dumps(batchless["work_orders"]),
            template="FG Pallet Label",
            carton_qty=batchless["carton_qty"],
            batch_no="",
        )

        self.assertIsNone(created["Label Record"].batch_no)
        self.assertIn("batch_no=&", result["print_url"])


class TestPalletLabelPrintSummaryPerBatch(unittest.TestCase):
    """Printed status belongs to a (Work Order, batch) pair, not to a Work Order.

    A Work Order that booked two batches appears in both of its rows. Counted by
    Work Order alone, printing one batch's labels marks the other batch's row as
    printed and the operator skips a pallet that was never labelled.
    """

    def _reads(self, records):
        def get_all(doctype, **kwargs):
            if doctype == "Label Record Source":
                return [frappe._dict(source_docname="WO-001", parent=r["name"]) for r in records]
            if doctype == "Label Record":
                return [frappe._dict(**r) for r in records]
            return []
        return get_all

    def _record(self, name, batch_no, creation="2026-09-15 09:00:00"):
        return {"name": name, "batch_no": batch_no, "creation": creation,
                "payload": json.dumps({"pallet_type": "EURO 1", "carton_qty": 100})}

    @patch('frappe.get_all')
    def test_a_batch_only_counts_labels_of_that_batch(self, mock_get_all):
        mock_get_all.side_effect = self._reads([
            self._record("LBL-A", "MJB-079"),
            self._record("LBL-B", "BBJ-504"),
        ])

        self.assertEqual(_pallet_label_print_summary(["WO-001"], "MJB-079")["label_count"], 1)
        self.assertEqual(_pallet_label_print_summary(["WO-001"], "BBJ-504")["label_count"], 1)

    @patch('frappe.get_all')
    def test_printing_one_batch_leaves_the_other_batch_unprinted(self, mock_get_all):
        """The reported failure mode: only MJB-079 was printed."""
        mock_get_all.side_effect = self._reads([self._record("LBL-A", "MJB-079")])

        printed = _pallet_label_print_summary(["WO-001"], "MJB-079")
        unprinted = _pallet_label_print_summary(["WO-001"], "BBJ-504")

        self.assertEqual(printed["printed_wo_count"], 1)
        self.assertEqual(unprinted["printed_wo_count"], 0)
        self.assertEqual(unprinted["label_count"], 0)
        self.assertIsNone(unprinted["last_printed_on"])

    @patch('frappe.get_all')
    def test_records_predating_batch_stamping_count_only_for_the_batchless_row(self, mock_get_all):
        """They carry no batch, so they cannot be attributed to one.

        Counting them for every batch would over-report and leave a pallet
        unlabelled; counting them for none costs at worst a duplicate label.
        """
        mock_get_all.side_effect = self._reads([self._record("LBL-OLD", None)])

        self.assertEqual(_pallet_label_print_summary(["WO-001"], "MJB-079")["label_count"], 0)
        self.assertEqual(_pallet_label_print_summary(["WO-001"], None)["label_count"], 1)

    @patch('frappe.get_all')
    def test_a_carton_label_record_is_still_ignored(self, mock_get_all):
        """Only pallet prints count — a carton Label Record has no pallet_type."""
        carton = {"name": "LBL-C", "batch_no": "MJB-079", "creation": "2026-09-15 09:00:00",
                  "payload": "Print Format: SATO FG Label Print"}
        mock_get_all.side_effect = self._reads([carton])

        self.assertEqual(_pallet_label_print_summary(["WO-001"], "MJB-079")["label_count"], 0)



if __name__ == "__main__":
    unittest.main()
