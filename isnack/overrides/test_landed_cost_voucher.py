# Copyright (c) 2024, Busuttil Technologies Limited
# License: MIT
# Tests for CustomLandedCostVoucher and sync_draft_assets_for_receipt

import unittest
from unittest.mock import MagicMock, call, patch

from frappe.utils import flt

from isnack.overrides.landed_cost_voucher import (
    RECEIPT_FIELD_MAP,
    sync_draft_assets_for_receipt,
)


def _make_frappe_mock(db_exists=True, fixed_asset_items=None, draft_assets=None):
    """Return a mock frappe module pre-configured for common test scenarios."""
    mock_frappe = MagicMock()
    mock_frappe.db.exists.return_value = db_exists
    mock_frappe.get_all.side_effect = _make_get_all(fixed_asset_items, draft_assets)
    mock_frappe.throw.side_effect = Exception  # make frappe.throw raise so we can catch it
    return mock_frappe


def _make_get_all(fixed_asset_items, draft_assets):
    """Return a side_effect function for frappe.get_all."""
    call_count = [0]

    def _side_effect(doctype, *args, **kwargs):
        if "Item" in doctype:  # child doctype call
            return fixed_asset_items or []
        # second call: Asset
        return draft_assets or []

    return _side_effect


# ---------------------------------------------------------------------------
# RECEIPT_FIELD_MAP sanity checks
# ---------------------------------------------------------------------------

class TestReceiptFieldMap(unittest.TestCase):
    def test_purchase_receipt_fields(self):
        m = RECEIPT_FIELD_MAP["Purchase Receipt"]
        self.assertEqual(m["parent_field"], "purchase_receipt")
        self.assertEqual(m["item_field"], "purchase_receipt_item")
        self.assertEqual(m["child_doctype"], "Purchase Receipt Item")

    def test_purchase_invoice_fields(self):
        m = RECEIPT_FIELD_MAP["Purchase Invoice"]
        self.assertEqual(m["parent_field"], "purchase_invoice")
        self.assertEqual(m["item_field"], "purchase_invoice_item")
        self.assertEqual(m["child_doctype"], "Purchase Invoice Item")


# ---------------------------------------------------------------------------
# sync_draft_assets_for_receipt — unsupported type
# ---------------------------------------------------------------------------

class TestSyncDraftAssetsUnsupportedType(unittest.TestCase):
    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_unsupported_receipt_type_raises(self, mock_frappe):
        mock_frappe.throw.side_effect = Exception("thrown")
        with self.assertRaises(Exception):
            sync_draft_assets_for_receipt("Stock Entry", "STE-0001")
        mock_frappe.throw.assert_called_once()


# ---------------------------------------------------------------------------
# sync_draft_assets_for_receipt — receipt does not exist
# ---------------------------------------------------------------------------

class TestSyncDraftAssetsReceiptNotFound(unittest.TestCase):
    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_nonexistent_receipt_raises(self, mock_frappe):
        mock_frappe.db.exists.return_value = False
        mock_frappe.throw.side_effect = Exception("thrown")
        with self.assertRaises(Exception):
            sync_draft_assets_for_receipt("Purchase Receipt", "MAT-PRE-9999")
        mock_frappe.throw.assert_called_once()


# ---------------------------------------------------------------------------
# sync_draft_assets_for_receipt — no fixed asset items
# ---------------------------------------------------------------------------

class TestSyncDraftAssetsNoItems(unittest.TestCase):
    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_no_fixed_asset_items_returns_empty_list(self, mock_frappe):
        mock_frappe.db.exists.return_value = True
        mock_frappe.get_all.return_value = []
        mock_frappe.logger.return_value = MagicMock()

        result = sync_draft_assets_for_receipt("Purchase Receipt", "MAT-PRE-0001")

        self.assertEqual(result, [])
        # frappe.db.set_value must NOT have been called
        mock_frappe.db.set_value.assert_not_called()


# ---------------------------------------------------------------------------
# sync_draft_assets_for_receipt — no linked draft assets
# ---------------------------------------------------------------------------

class TestSyncDraftAssetsNoAssets(unittest.TestCase):
    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_no_linked_assets_returns_empty(self, mock_frappe):
        mock_frappe.db.exists.return_value = True
        mock_frappe.logger.return_value = MagicMock()

        # First call returns fixed asset items; second call returns no assets
        mock_frappe.get_all.side_effect = [
            [{"name": "row-1", "item_code": "ITEM-A", "valuation_rate": 500.0}],
            [],
        ]

        result = sync_draft_assets_for_receipt("Purchase Receipt", "MAT-PRE-0001")

        self.assertEqual(result, [])
        mock_frappe.db.set_value.assert_not_called()


# ---------------------------------------------------------------------------
# sync_draft_assets_for_receipt — updates without depreciation
# ---------------------------------------------------------------------------

class TestSyncDraftAssetsUpdatesWithoutDepreciation(unittest.TestCase):
    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_updates_gross_and_purchase_amount(self, mock_frappe):
        mock_frappe.db.exists.return_value = True
        mock_frappe.logger.return_value = MagicMock()

        item = {"name": "row-1", "item_code": "ITEM-A", "valuation_rate": 784.72}
        asset = {
            "name": "ACC-ASS-00001",
            "purchase_receipt_item": None,  # blank → loose match
            "asset_quantity": 1,
            "gross_purchase_amount": 700.0,
            "purchase_amount": 700.0,
            "additional_asset_cost": 0.0,
            "opening_accumulated_depreciation": 0.0,
            "calculate_depreciation": 0,
        }

        mock_frappe.get_all.side_effect = [[item], [asset]]

        result = sync_draft_assets_for_receipt("Purchase Receipt", "MAT-PRE-0132")

        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["new_amount"], 784.72)
        self.assertAlmostEqual(result[0]["old_amount"], 700.0)
        self.assertEqual(result[0]["asset"], "ACC-ASS-00001")

        mock_frappe.db.set_value.assert_called_once_with(
            "Asset",
            "ACC-ASS-00001",
            {
                "gross_purchase_amount": 784.72,
                "purchase_amount": 784.72,
                "total_asset_cost": 784.72,
            },
        )


# ---------------------------------------------------------------------------
# sync_draft_assets_for_receipt — updates with depreciation
# ---------------------------------------------------------------------------

class TestSyncDraftAssetsUpdatesWithDepreciation(unittest.TestCase):
    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_updates_value_after_depreciation_when_enabled(self, mock_frappe):
        mock_frappe.db.exists.return_value = True
        mock_frappe.logger.return_value = MagicMock()

        item = {"name": "row-1", "item_code": "ITEM-B", "valuation_rate": 1000.0}
        asset = {
            "name": "ACC-ASS-00002",
            "purchase_receipt_item": None,
            "asset_quantity": 1,
            "gross_purchase_amount": 900.0,
            "purchase_amount": 900.0,
            "additional_asset_cost": 50.0,
            "opening_accumulated_depreciation": 100.0,
            "calculate_depreciation": 1,
        }

        mock_frappe.get_all.side_effect = [[item], [asset]]

        result = sync_draft_assets_for_receipt("Purchase Receipt", "MAT-PRE-0002")

        self.assertEqual(len(result), 1)
        expected_purchase = 1000.0 * 1  # valuation_rate × qty
        expected_total = expected_purchase + 50.0  # + additional_asset_cost
        expected_val_after_dep = expected_purchase - 100.0  # - opening_accumulated_depreciation

        mock_frappe.db.set_value.assert_called_once_with(
            "Asset",
            "ACC-ASS-00002",
            {
                "gross_purchase_amount": expected_purchase,
                "purchase_amount": expected_purchase,
                "total_asset_cost": expected_total,
                "value_after_depreciation": expected_val_after_dep,
            },
        )


# ---------------------------------------------------------------------------
# sync_draft_assets_for_receipt — asset_quantity defaults to 1 when 0 or None
# ---------------------------------------------------------------------------

class TestAssetQuantityDefault(unittest.TestCase):
    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_zero_asset_quantity_defaults_to_one(self, mock_frappe):
        mock_frappe.db.exists.return_value = True
        mock_frappe.logger.return_value = MagicMock()

        item = {"name": "row-1", "item_code": "ITEM-C", "valuation_rate": 500.0}
        asset = {
            "name": "ACC-ASS-00003",
            "purchase_receipt_item": None,
            "asset_quantity": 0,  # should default to 1
            "gross_purchase_amount": 0.0,
            "purchase_amount": 0.0,
            "additional_asset_cost": 0.0,
            "opening_accumulated_depreciation": 0.0,
            "calculate_depreciation": 0,
        }

        mock_frappe.get_all.side_effect = [[item], [asset]]

        result = sync_draft_assets_for_receipt("Purchase Receipt", "MAT-PRE-0003")

        self.assertAlmostEqual(result[0]["new_amount"], 500.0)

    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_none_asset_quantity_defaults_to_one(self, mock_frappe):
        mock_frappe.db.exists.return_value = True
        mock_frappe.logger.return_value = MagicMock()

        item = {"name": "row-1", "item_code": "ITEM-C", "valuation_rate": 500.0}
        asset = {
            "name": "ACC-ASS-00003",
            "purchase_receipt_item": None,
            "asset_quantity": None,
            "gross_purchase_amount": 0.0,
            "purchase_amount": 0.0,
            "additional_asset_cost": None,
            "opening_accumulated_depreciation": None,
            "calculate_depreciation": 0,
        }

        mock_frappe.get_all.side_effect = [[item], [asset]]

        result = sync_draft_assets_for_receipt("Purchase Receipt", "MAT-PRE-0003")

        self.assertAlmostEqual(result[0]["new_amount"], 500.0)


# ---------------------------------------------------------------------------
# sync_draft_assets_for_receipt — child-row reference filtering
# ---------------------------------------------------------------------------

class TestChildRowFiltering(unittest.TestCase):
    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_asset_with_matching_child_row_is_updated(self, mock_frappe):
        mock_frappe.db.exists.return_value = True
        mock_frappe.logger.return_value = MagicMock()

        item = {"name": "row-exact", "item_code": "ITEM-D", "valuation_rate": 300.0}
        asset_match = {
            "name": "ACC-ASS-00010",
            "purchase_receipt_item": "row-exact",  # matches
            "asset_quantity": 1,
            "gross_purchase_amount": 0.0,
            "purchase_amount": 0.0,
            "additional_asset_cost": 0.0,
            "opening_accumulated_depreciation": 0.0,
            "calculate_depreciation": 0,
        }
        asset_no_match = {
            "name": "ACC-ASS-00011",
            "purchase_receipt_item": "row-other",  # does NOT match
            "asset_quantity": 1,
            "gross_purchase_amount": 0.0,
            "purchase_amount": 0.0,
            "additional_asset_cost": 0.0,
            "opening_accumulated_depreciation": 0.0,
            "calculate_depreciation": 0,
        }

        mock_frappe.get_all.side_effect = [[item], [asset_match, asset_no_match]]

        result = sync_draft_assets_for_receipt("Purchase Receipt", "MAT-PRE-0004")

        # Only the matching asset should be updated
        updated_names = [r["asset"] for r in result]
        self.assertIn("ACC-ASS-00010", updated_names)
        self.assertNotIn("ACC-ASS-00011", updated_names)

    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_asset_with_blank_child_row_ref_is_updated_loosely(self, mock_frappe):
        mock_frappe.db.exists.return_value = True
        mock_frappe.logger.return_value = MagicMock()

        item = {"name": "row-1", "item_code": "ITEM-E", "valuation_rate": 200.0}
        asset = {
            "name": "ACC-ASS-00012",
            "purchase_receipt_item": "",  # blank → loose match
            "asset_quantity": 1,
            "gross_purchase_amount": 0.0,
            "purchase_amount": 0.0,
            "additional_asset_cost": 0.0,
            "opening_accumulated_depreciation": 0.0,
            "calculate_depreciation": 0,
        }

        mock_frappe.get_all.side_effect = [[item], [asset]]

        result = sync_draft_assets_for_receipt("Purchase Receipt", "MAT-PRE-0005")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["asset"], "ACC-ASS-00012")


# ---------------------------------------------------------------------------
# sync_draft_assets_for_receipt — Purchase Invoice support
# ---------------------------------------------------------------------------

class TestPurchaseInvoiceSupport(unittest.TestCase):
    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_purchase_invoice_uses_correct_fields(self, mock_frappe):
        mock_frappe.db.exists.return_value = True
        mock_frappe.logger.return_value = MagicMock()

        item = {"name": "row-pi-1", "item_code": "ITEM-F", "valuation_rate": 600.0}
        asset = {
            "name": "ACC-ASS-00020",
            "purchase_invoice_item": None,
            "asset_quantity": 1,
            "gross_purchase_amount": 0.0,
            "purchase_amount": 0.0,
            "additional_asset_cost": 0.0,
            "opening_accumulated_depreciation": 0.0,
            "calculate_depreciation": 0,
        }

        mock_frappe.get_all.side_effect = [[item], [asset]]

        result = sync_draft_assets_for_receipt("Purchase Invoice", "PINV-2026-00001")

        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["new_amount"], 600.0)

        # Verify get_all was called for Purchase Invoice Item child doctype
        first_call_args = mock_frappe.get_all.call_args_list[0]
        self.assertIn("Purchase Invoice Item", first_call_args[0])


# ---------------------------------------------------------------------------
# CustomLandedCostVoucher — _isnack_sync_draft_assets wraps errors
# ---------------------------------------------------------------------------

class TestCustomLandedCostVoucherSyncWrapsErrors(unittest.TestCase):
    @patch("isnack.overrides.landed_cost_voucher.sync_draft_assets_for_receipt")
    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_exception_in_sync_is_logged_not_raised(self, mock_frappe, mock_sync):
        """Errors in sync_draft_assets_for_receipt must never surface to the LCV transaction."""
        from isnack.overrides.landed_cost_voucher import CustomLandedCostVoucher

        mock_sync.side_effect = Exception("DB error")
        mock_frappe.get_traceback.return_value = "traceback text"

        lcv = CustomLandedCostVoucher.__new__(CustomLandedCostVoucher)

        row = MagicMock()
        row.receipt_document_type = "Purchase Receipt"
        row.receipt_document = "MAT-PRE-0001"
        lcv.get = MagicMock(return_value=[row])

        # Should NOT raise
        lcv._isnack_sync_draft_assets()

        mock_frappe.log_error.assert_called_once()

    @patch("isnack.overrides.landed_cost_voucher.sync_draft_assets_for_receipt")
    @patch("isnack.overrides.landed_cost_voucher.frappe")
    def test_empty_purchase_receipts_does_nothing(self, mock_frappe, mock_sync):
        from isnack.overrides.landed_cost_voucher import CustomLandedCostVoucher

        lcv = CustomLandedCostVoucher.__new__(CustomLandedCostVoucher)
        lcv.get = MagicMock(return_value=[])

        lcv._isnack_sync_draft_assets()

        mock_sync.assert_not_called()


if __name__ == "__main__":
    unittest.main()
