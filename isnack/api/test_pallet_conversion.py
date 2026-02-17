# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import patch, MagicMock

import frappe
from isnack.api.mes_ops import get_pallet_conversion_factor


class TestPalletConversionFactor(unittest.TestCase):
    """Tests for pallet UOM conversion factor calculation."""
    
    @patch('isnack.api.mes_ops._require_roles')
    def test_same_uom_returns_one(self, mock_require_roles):
        """Test that same UOM returns conversion factor of 1.0 with found=True."""
        result = get_pallet_conversion_factor("ITEM001", "Carton", "Carton")
        self.assertEqual(result["conversion_factor"], 1.0)
        self.assertTrue(result["found"])
    
    @patch('isnack.api.mes_ops._require_roles')
    def test_missing_parameters_returns_not_found(self, mock_require_roles):
        """Test that missing parameters return found=False."""
        result = get_pallet_conversion_factor("", "Carton", "Pallet")
        self.assertFalse(result["found"])
        self.assertIsNone(result["conversion_factor"])
        
        result = get_pallet_conversion_factor("ITEM001", "", "Pallet")
        self.assertFalse(result["found"])
        self.assertIsNone(result["conversion_factor"])
        
        result = get_pallet_conversion_factor("ITEM001", "Carton", "")
        self.assertFalse(result["found"])
        self.assertIsNone(result["conversion_factor"])
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_cached_value')
    @patch('frappe.get_all')
    def test_item_uom_conversion_found(self, mock_get_all, mock_get_cached_value, mock_require_roles):
        """Test conversion using item-specific UOM conversion."""
        # Mock item with stock UOM
        mock_get_cached_value.return_value = {"stock_uom": "Nos"}
        
        # Mock UOM conversion details for the item
        # First call: from_uom (Carton) = 24 Nos
        # Second call: to_uom (EUR 1 Pallet) = 96 Nos
        mock_get_all.side_effect = [
            [{"conversion_factor": 24.0}],  # 1 Carton = 24 Nos
            [{"conversion_factor": 96.0}],  # 1 EUR 1 Pallet = 96 Nos
        ]
        
        result = get_pallet_conversion_factor("FG10015", "Carton", "EUR 1 Pallet")
        
        # Conversion should be 96/24 = 4 (meaning 1 Pallet = 4 Cartons)
        # So 10 Cartons / 4 = 2.5 Pallets
        self.assertTrue(result["found"])
        self.assertAlmostEqual(result["conversion_factor"], 4.0, places=6)
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_cached_value')
    @patch('frappe.get_all')
    def test_item_uom_from_stock_uom(self, mock_get_all, mock_get_cached_value, mock_require_roles):
        """Test conversion when from_uom is the stock UOM."""
        # Mock item with stock UOM
        mock_get_cached_value.return_value = {"stock_uom": "Carton"}
        
        # Mock UOM conversion details for the item
        # Only need to_uom since from_uom = stock_uom
        mock_get_all.side_effect = [
            [{"conversion_factor": 4.0}],  # 1 EUR 1 Pallet = 4 Cartons
        ]
        
        result = get_pallet_conversion_factor("FG10015", "Carton", "EUR 1 Pallet")
        
        # Conversion should be 4.0/1.0 = 4.0
        # So 10 Cartons / 4 = 2.5 Pallets
        self.assertTrue(result["found"])
        self.assertAlmostEqual(result["conversion_factor"], 4.0, places=6)
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_cached_value')
    @patch('frappe.get_all')
    def test_global_uom_conversion_found(self, mock_get_all, mock_get_cached_value, mock_require_roles):
        """Test conversion using global UOM Conversion Factor table."""
        # Mock item with stock UOM
        mock_get_cached_value.return_value = {"stock_uom": "Nos"}
        
        # Mock UOM conversion details - not found on item
        # First two calls for item UOMs (empty results)
        # Third call for global UOM conversion
        mock_get_all.side_effect = [
            [],  # from_uom not on item
            [],  # to_uom not on item
            [{"value": 0.5}],  # Global conversion found
        ]
        
        result = get_pallet_conversion_factor("ITEM001", "Box", "Pallet")
        
        self.assertTrue(result["found"])
        self.assertEqual(result["conversion_factor"], 0.5)
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_cached_value')
    @patch('frappe.get_all')
    def test_global_uom_inverse_conversion(self, mock_get_all, mock_get_cached_value, mock_require_roles):
        """Test inverse conversion in global UOM Conversion Factor table."""
        # Mock item with stock UOM
        mock_get_cached_value.return_value = {"stock_uom": "Nos"}
        
        # Mock UOM conversion details - not found on item
        # First two calls for item UOMs (empty results)
        # Third call for global UOM conversion (not found)
        # Fourth call for inverse conversion
        mock_get_all.side_effect = [
            [],  # from_uom not on item
            [],  # to_uom not on item
            [],  # Global conversion not found
            [{"value": 2.0}],  # Inverse conversion found (to_uom->from_uom)
        ]
        
        result = get_pallet_conversion_factor("ITEM001", "Box", "Pallet")
        
        # If Pallet->Box = 2.0, then Box->Pallet = 1/2.0 = 0.5
        self.assertTrue(result["found"])
        self.assertAlmostEqual(result["conversion_factor"], 0.5, places=6)
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_cached_value')
    @patch('frappe.get_all')
    def test_no_conversion_found(self, mock_get_all, mock_get_cached_value, mock_require_roles):
        """Test that no conversion returns found=False with null conversion_factor."""
        # Mock item with stock UOM
        mock_get_cached_value.return_value = {"stock_uom": "Nos"}
        
        # Mock all lookups returning empty
        mock_get_all.return_value = []
        
        result = get_pallet_conversion_factor("ITEM001", "Box", "Pallet")
        
        self.assertFalse(result["found"])
        self.assertIsNone(result["conversion_factor"])
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_cached_value')
    @patch('frappe.get_all')
    def test_partial_item_conversion_not_found(self, mock_get_all, mock_get_cached_value, mock_require_roles):
        """Test that partial item conversions (only one UOM found) fall back to global."""
        # Mock item with stock UOM
        mock_get_cached_value.return_value = {"stock_uom": "Nos"}
        
        # Mock UOM conversion details - only from_uom found on item
        # First call: from_uom found
        # Second call: to_uom not found on item
        # Third call: global conversion
        mock_get_all.side_effect = [
            [{"conversion_factor": 24.0}],  # from_uom on item
            [],  # to_uom not on item
            [{"value": 0.25}],  # Global conversion found
        ]
        
        result = get_pallet_conversion_factor("ITEM001", "Carton", "Pallet")
        
        # Should fall back to global conversion
        self.assertTrue(result["found"])
        self.assertEqual(result["conversion_factor"], 0.25)
    
    @patch('isnack.api.mes_ops._require_roles')
    @patch('frappe.get_cached_value')
    @patch('frappe.get_all')
    @patch('frappe.log_error')
    def test_error_handling(self, mock_log_error, mock_get_all, mock_get_cached_value, mock_require_roles):
        """Test that exceptions are logged and return found=False."""
        # Mock item with stock UOM
        mock_get_cached_value.return_value = {"stock_uom": "Nos"}
        
        # Mock get_all to raise an exception
        mock_get_all.side_effect = Exception("Database error")
        
        result = get_pallet_conversion_factor("ITEM001", "Box", "Pallet")
        
        # Should return not found
        self.assertFalse(result["found"])
        self.assertIsNone(result["conversion_factor"])
        
        # Error should be logged
        mock_log_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
