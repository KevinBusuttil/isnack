# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Tests for raw-material scan parsing separator compatibility.

The collective raw-material QR payload is canonically pipe-separated
("ITEM_CODE|BATCH_NO|QUANTITY"), but some USB scanners on a different keyboard
layout emit a tilde ("~") instead of the pipe. The parser must accept both
forms as equivalent while leaving GS1 parsing untouched.
"""

import unittest
from unittest.mock import patch

import frappe
from isnack.api.mes_ops import _parse_gs1_or_basic, parse_scan


class TestParseScanSeparators(unittest.TestCase):
    """Separator compatibility for the basic ITEM|BATCH|QTY fallback."""

    # --- (a) / (b) standard payload, pipe and tilde ---------------------

    def test_pipe_standard(self):
        out = _parse_gs1_or_basic("RM20021|254193336|76.8")
        self.assertEqual(out["item_code"], "RM20021")
        self.assertEqual(out["batch_no"], "254193336")
        self.assertEqual(out["qty"], 76.8)

    def test_tilde_standard(self):
        out = _parse_gs1_or_basic("RM20021~254193336~76.8")
        self.assertEqual(out["item_code"], "RM20021")
        self.assertEqual(out["batch_no"], "254193336")
        self.assertEqual(out["qty"], 76.8)

    def test_pipe_and_tilde_are_equivalent(self):
        self.assertEqual(
            _parse_gs1_or_basic("RM20021|254193336|76.8"),
            _parse_gs1_or_basic("RM20021~254193336~76.8"),
        )

    # --- (c) / (d) empty batch field, pipe and tilde --------------------

    def test_pipe_empty_batch(self):
        out = _parse_gs1_or_basic("RM20023||5.334")
        self.assertEqual(out["item_code"], "RM20023")
        self.assertEqual(out["batch_no"], "")
        self.assertEqual(out["qty"], 5.334)

    def test_tilde_empty_batch(self):
        out = _parse_gs1_or_basic("RM20023~~5.334")
        self.assertEqual(out["item_code"], "RM20023")
        self.assertEqual(out["batch_no"], "")
        self.assertEqual(out["qty"], 5.334)

    # --- (e) invalid / non-numeric quantity -----------------------------

    def test_pipe_invalid_qty_dropped(self):
        out = _parse_gs1_or_basic("RM20021|254193336|abc")
        self.assertEqual(out["item_code"], "RM20021")
        self.assertEqual(out["batch_no"], "254193336")
        self.assertNotIn("qty", out)

    def test_tilde_invalid_qty_dropped(self):
        out = _parse_gs1_or_basic("RM20021~254193336~abc")
        self.assertEqual(out["item_code"], "RM20021")
        self.assertEqual(out["batch_no"], "254193336")
        self.assertNotIn("qty", out)

    # --- (f) GS1 input remains unaffected -------------------------------

    @patch("frappe.db.get_value")
    def test_gs1_unaffected(self, mock_get_value):
        # GTIN resolves to an item via Item Barcode, so the basic-format
        # fallback (where separator handling lives) is never reached.
        mock_get_value.return_value = "RM99999"
        out = _parse_gs1_or_basic("(01)00012345678905(10)CGB-151(30)12.5")
        self.assertEqual(out["item_code"], "RM99999")
        self.assertEqual(out["batch_no"], "CGB-151")
        self.assertEqual(out["qty"], 12.5)
        # The AI-derived batch must survive; it must not be overwritten by a
        # spurious pipe/tilde split of the GS1 string.
        self.assertNotIn("|", out["batch_no"])
        self.assertNotIn("~", out["batch_no"])

    # --- (g) mixed separators are accepted (approved in Phase 1) ---------

    def test_mixed_pipe_then_tilde(self):
        out = _parse_gs1_or_basic("RM20021|254193336~76.8")
        self.assertEqual(out["item_code"], "RM20021")
        self.assertEqual(out["batch_no"], "254193336")
        self.assertEqual(out["qty"], 76.8)

    def test_mixed_tilde_then_pipe(self):
        out = _parse_gs1_or_basic("RM20021~254193336|76.8")
        self.assertEqual(out["item_code"], "RM20021")
        self.assertEqual(out["batch_no"], "254193336")
        self.assertEqual(out["qty"], 76.8)

    # --- malformed payloads degrade the same for both separators --------

    def test_empty_code_yields_no_item(self):
        self.assertFalse(_parse_gs1_or_basic("").get("item_code"))

    def test_single_token_no_separator(self):
        out = _parse_gs1_or_basic("RM20021")
        self.assertEqual(out["item_code"], "RM20021")
        self.assertNotIn("qty", out)


class TestParseScanEndpoint(unittest.TestCase):
    """Operator Hub entry point (parse_scan) accepts both separators."""

    @patch("frappe.db.get_value")
    def test_parse_scan_pipe(self, mock_get_value):
        mock_get_value.return_value = "Kg"  # Item.stock_uom
        res = parse_scan("RM20021|254193336|76.8")
        self.assertTrue(res["ok"])
        self.assertEqual(res["item_code"], "RM20021")
        self.assertEqual(res["batch_no"], "254193336")
        self.assertEqual(res["barcode_qty"], 76.8)
        self.assertEqual(res["uom"], "Kg")

    @patch("frappe.db.get_value")
    def test_parse_scan_tilde(self, mock_get_value):
        mock_get_value.return_value = "Kg"  # Item.stock_uom
        res = parse_scan("RM20021~254193336~76.8")
        self.assertTrue(res["ok"])
        self.assertEqual(res["item_code"], "RM20021")
        self.assertEqual(res["batch_no"], "254193336")
        self.assertEqual(res["barcode_qty"], 76.8)
        self.assertEqual(res["uom"], "Kg")

    def test_parse_scan_unparseable(self):
        res = parse_scan("")
        self.assertFalse(res["ok"])


if __name__ == "__main__":
    unittest.main()
