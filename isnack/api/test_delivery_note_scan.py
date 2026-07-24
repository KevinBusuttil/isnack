# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Tests for the Delivery Note label-scan endpoint.

`scan_delivery_note_code` must recognise the label payloads printed by the
Operator Hub ("ITEM|BATCH|QTY", tilde-separated variants, GS1) and answer in
the shape ERPNext's BarcodeScanner expects, while delegating everything else
— bare item barcodes, bare batch numbers, unknown strings — to the stock
`erpnext.stock.utils.scan_barcode` lookup unchanged.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from isnack.api import delivery_note_scan


def _settings(**overrides):
    base = {
        "enabled": 1,
        "qty_mode": "Increment by Label Qty",
        "restrict_to_existing_items": 1,
    }
    base.update(overrides)
    return base


class TestDnScanSettings(unittest.TestCase):
    """Factory Settings are read with safe defaults for unset fields."""

    @patch("frappe.get_cached_doc")
    def test_unset_fields_fall_back_to_safe_defaults(self, mock_doc):
        fs = MagicMock()
        fs.get.return_value = None
        mock_doc.return_value = fs

        out = delivery_note_scan.get_dn_scan_settings()
        self.assertEqual(out["enabled"], 0)
        self.assertEqual(out["qty_mode"], delivery_note_scan.DEFAULT_QTY_MODE)
        # The checkbox default is ON, so "never saved" must not read as off.
        self.assertEqual(out["restrict_to_existing_items"], 1)

    @patch("frappe.get_cached_doc")
    def test_saved_values_are_respected_and_mode_sanitised(self, mock_doc):
        values = {
            "dn_scan_enabled": 1,
            "dn_scan_qty_mode": "Bogus Mode",
            "dn_scan_restrict_to_existing_items": 0,
        }
        fs = MagicMock()
        fs.get.side_effect = values.get
        mock_doc.return_value = fs

        out = delivery_note_scan.get_dn_scan_settings()
        self.assertEqual(out["enabled"], 1)
        self.assertEqual(out["qty_mode"], delivery_note_scan.DEFAULT_QTY_MODE)
        self.assertEqual(out["restrict_to_existing_items"], 0)


class TestCoreScanDelegation(unittest.TestCase):
    """Non-label input goes to the stock lookup verbatim."""

    @patch.object(delivery_note_scan, "_core_scan")
    @patch.object(delivery_note_scan, "get_dn_scan_settings")
    def test_disabled_feature_proxies_everything(self, mock_settings, mock_core):
        mock_settings.return_value = _settings(enabled=0)
        mock_core.return_value = {"item_code": "X"}

        out = delivery_note_scan.scan_delivery_note_code("FG10011|CGB-151|66", {"a": 1})
        self.assertEqual(out, {"item_code": "X"})
        mock_core.assert_called_once_with("FG10011|CGB-151|66", {"a": 1})

    @patch.object(delivery_note_scan, "_core_scan")
    @patch.object(delivery_note_scan, "get_dn_scan_settings")
    def test_bare_token_goes_to_stock_lookup(self, mock_settings, mock_core):
        # A bare batch number (or item barcode) has no separator, so the
        # stock lookup keeps owning it — it already resolves Batch names.
        mock_settings.return_value = _settings()
        mock_core.return_value = {"batch_no": "CGB-151", "item_code": "FG10011"}

        out = delivery_note_scan.scan_delivery_note_code("CGB-151")
        self.assertEqual(out["batch_no"], "CGB-151")
        mock_core.assert_called_once_with("CGB-151", None)

    @patch.object(delivery_note_scan, "_core_scan")
    @patch.object(delivery_note_scan, "get_dn_scan_settings")
    def test_empty_input_goes_to_stock_lookup(self, mock_settings, mock_core):
        mock_settings.return_value = _settings()
        mock_core.return_value = {}

        self.assertEqual(delivery_note_scan.scan_delivery_note_code(""), {})
        mock_core.assert_called_once_with("", None)

    @patch("frappe.db.exists")
    @patch("frappe.db.get_value")
    @patch.object(delivery_note_scan, "_core_scan")
    @patch.object(delivery_note_scan, "get_dn_scan_settings")
    def test_gs1_with_unknown_gtin_goes_to_stock_lookup(
        self, mock_settings, mock_core, mock_get_value, mock_exists
    ):
        # The parser cannot resolve the GTIN, so its fallback treats the whole
        # GS1 string as "item_code" — that scan is somebody else's barcode and
        # must be delegated, not rejected with a label error.
        mock_settings.return_value = _settings()
        mock_core.return_value = {}
        mock_get_value.return_value = None  # Item Barcode lookup misses
        mock_exists.return_value = False  # raw GS1 string is not an Item

        payload = "(01)99912345678905(10)CGB-151(30)12.5"
        self.assertEqual(delivery_note_scan.scan_delivery_note_code(payload), {})
        mock_core.assert_called_once_with(payload, None)


class TestLabelScan(unittest.TestCase):
    """Label payloads are validated and answered in scanner shape."""

    def _scan(self, payload, ctx=None, batch_item="FG10011", item_exists=True,
              has_serial_no=0, settings=None):
        with patch.object(
            delivery_note_scan, "get_dn_scan_settings",
            return_value=settings or _settings(),
        ), patch("frappe.db.exists", return_value=item_exists), patch(
            "frappe.db.get_value", return_value=batch_item
        ), patch(
            "frappe.get_cached_value",
            return_value=frappe._dict(
                has_batch_no=1, has_serial_no=has_serial_no, stock_uom="Carton"
            ),
        ):
            return delivery_note_scan.scan_delivery_note_code(payload, ctx)

    def test_pipe_label_full_response(self):
        out = self._scan("FG10011|CGB-151|66")
        self.assertEqual(out["item_code"], "FG10011")
        self.assertEqual(out["batch_no"], "CGB-151")
        self.assertEqual(out["has_batch_no"], 1)
        self.assertEqual(out["isnack_label_scan"], 1)
        self.assertEqual(out["isnack_scanned_qty"], 66.0)
        self.assertEqual(out["isnack_stock_uom"], "Carton")
        self.assertEqual(out["isnack_qty_mode"], "Increment by Label Qty")
        self.assertEqual(out["isnack_restrict_to_existing_items"], 1)

    def test_tilde_label_equals_pipe_label(self):
        self.assertEqual(
            self._scan("FG10011|CGB-151|66"), self._scan("FG10011~CGB-151~66")
        )

    def test_label_without_qty(self):
        out = self._scan("FG10011|CGB-151")
        self.assertEqual(out["isnack_scanned_qty"], 0)

    def test_label_with_empty_batch_skips_batch_validation(self):
        out = self._scan("FG10011||66", batch_item=None)
        self.assertNotIn("batch_no", out)
        self.assertEqual(out["isnack_scanned_qty"], 66.0)

    def test_unknown_item_on_label_is_a_specific_error(self):
        with self.assertRaises(frappe.ValidationError):
            self._scan("FG99999|CGB-151|66", item_exists=False)

    def test_unknown_batch_is_a_specific_error(self):
        with self.assertRaises(frappe.ValidationError):
            self._scan("FG10011|NOPE-999|66", batch_item=None)

    def test_batch_of_another_item_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self._scan("FG10011|CGB-151|66", batch_item="FG10012")

    def test_serialised_item_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self._scan("FG10011|CGB-151|66", has_serial_no=1)

    def test_qty_mode_is_echoed_from_settings(self):
        out = self._scan(
            "FG10011|CGB-151|66", settings=_settings(qty_mode="Assign Batch Only")
        )
        self.assertEqual(out["isnack_qty_mode"], "Assign Batch Only")


class TestStockWarning(unittest.TestCase):
    """The zero-stock warning is advisory and never breaks the scan."""

    def _scan(self, ctx, batch_qty):
        with patch.object(
            delivery_note_scan, "get_dn_scan_settings", return_value=_settings()
        ), patch("frappe.db.exists", return_value=True), patch(
            "frappe.db.get_value", return_value="FG10011"
        ), patch(
            "frappe.get_cached_value",
            return_value=frappe._dict(
                has_batch_no=1, has_serial_no=0, stock_uom="Carton"
            ),
        ), patch.object(
            delivery_note_scan, "get_batch_qty", return_value=batch_qty
        ):
            return delivery_note_scan.scan_delivery_note_code("FG10011|CGB-151|66", ctx)

    def test_zero_stock_adds_warning(self):
        out = self._scan({"set_warehouse": "Finished Goods - ISN"}, 0)
        self.assertIn("isnack_stock_warning", out)
        self.assertIn("CGB-151", out["isnack_stock_warning"])

    def test_available_stock_adds_no_warning(self):
        out = self._scan({"set_warehouse": "Finished Goods - ISN"}, 132)
        self.assertNotIn("isnack_stock_warning", out)

    def test_missing_ctx_skips_the_check(self):
        out = self._scan(None, 0)
        self.assertNotIn("isnack_stock_warning", out)

    def test_broken_stock_lookup_is_swallowed(self):
        with patch.object(
            delivery_note_scan, "get_dn_scan_settings", return_value=_settings()
        ), patch("frappe.db.exists", return_value=True), patch(
            "frappe.db.get_value", return_value="FG10011"
        ), patch(
            "frappe.get_cached_value",
            return_value=frappe._dict(
                has_batch_no=1, has_serial_no=0, stock_uom="Carton"
            ),
        ), patch.object(
            delivery_note_scan, "get_batch_qty", side_effect=Exception("boom")
        ):
            out = delivery_note_scan.scan_delivery_note_code(
                "FG10011|CGB-151|66", {"set_warehouse": "Finished Goods - ISN"}
            )
        self.assertNotIn("isnack_stock_warning", out)


class TestCoreScanSignatureTolerance(unittest.TestCase):
    """_core_scan works with both v15 signatures of the stock lookup."""

    def test_modern_signature_receives_ctx(self):
        def modern(search_value, ctx=None):
            return {"got_ctx": ctx}

        with patch.object(delivery_note_scan, "_erpnext_scan_barcode", modern):
            out = delivery_note_scan._core_scan("x", {"a": 1})
        self.assertEqual(out, {"got_ctx": {"a": 1}})

    def test_legacy_signature_is_called_without_ctx(self):
        def legacy(search_value):
            return {"ok": True}

        with patch.object(delivery_note_scan, "_erpnext_scan_barcode", legacy):
            out = delivery_note_scan._core_scan("x", {"a": 1})
        self.assertEqual(out, {"ok": True})

    def test_empty_result_becomes_empty_dict(self):
        def nothing(search_value):
            return None

        with patch.object(delivery_note_scan, "_erpnext_scan_barcode", nothing):
            self.assertEqual(delivery_note_scan._core_scan("x"), {})


if __name__ == "__main__":
    unittest.main()
