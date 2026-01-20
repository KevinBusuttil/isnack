# Copyright (c) 2024, Busuttil Technologies Limited
# License: MIT
# Tests for CustomJournalEntry to ensure correct handling of multi-currency JEs

import unittest
from unittest.mock import MagicMock, patch

from frappe.utils import flt


class TestSetAmountsInCompanyCurrency(unittest.TestCase):
    """Tests for set_amounts_in_company_currency method."""
    
    def setUp(self):
        """Set up test fixtures."""
        # We'll mock the CustomJournalEntry to test the logic
        self.patcher_frappe_db = patch('isnack.overrides.journal_entry.frappe.db')
        self.mock_frappe_db = self.patcher_frappe_db.start()
    
    def tearDown(self):
        """Clean up patches."""
        self.patcher_frappe_db.stop()
    
    def create_mock_je(self, multi_currency=False, cheque_no=None, voucher_type="Journal Entry"):
        """Create a mock Journal Entry document."""
        from isnack.overrides.journal_entry import CustomJournalEntry
        
        je = CustomJournalEntry()
        je.multi_currency = multi_currency
        je.cheque_no = cheque_no
        je.voucher_type = voucher_type
        je.accounts = []
        return je
    
    def add_account_row(self, je, debit=0, credit=0, debit_in_account_currency=0, 
                       credit_in_account_currency=0, exchange_rate=1.0):
        """Add an account row to the journal entry."""
        row = MagicMock()
        row.debit = debit
        row.credit = credit
        row.debit_in_account_currency = debit_in_account_currency
        row.credit_in_account_currency = credit_in_account_currency
        row.exchange_rate = exchange_rate
        
        # Mock precision method
        row.precision = lambda field: 2
        
        je.accounts.append(row)
        return row
    
    def test_single_currency_je_uses_standard_behavior(self):
        """
        Test: Single-currency JE should use standard ERPNext behavior.
        Expected: debit = debit_in_account_currency × exchange_rate
        """
        # Create single-currency JE (multi_currency=False)
        je = self.create_mock_je(multi_currency=False)
        
        # Add a row with account currency amounts only
        row = self.add_account_row(
            je,
            debit=0,  # Company amount not set
            debit_in_account_currency=100.0,
            exchange_rate=1.0
        )
        
        # Call the method
        je.set_amounts_in_company_currency()
        
        # Verify standard behavior: debit = debit_in_account_currency × exchange_rate
        self.assertEqual(flt(row.debit), 100.0)
        self.assertEqual(flt(row.debit_in_account_currency), 100.0)
    
    def test_multi_currency_je_not_from_service_invoice_uses_standard_behavior(self):
        """
        Test: Multi-currency JE not from Service Invoice should use standard ERPNext behavior.
        Expected: debit = debit_in_account_currency × exchange_rate
        """
        # Create multi-currency JE without cheque_no
        je = self.create_mock_je(multi_currency=True, cheque_no=None)
        
        # Add a row with account currency amounts only
        row = self.add_account_row(
            je,
            debit=0,  # Company amount not set
            debit_in_account_currency=100.0,
            exchange_rate=1.2
        )
        
        # Call the method
        je.set_amounts_in_company_currency()
        
        # Verify standard behavior: debit = 100.0 × 1.2 = 120.0
        self.assertEqual(flt(row.debit), 120.0)
        self.assertEqual(flt(row.debit_in_account_currency), 100.0)
    
    def test_multi_currency_je_from_service_invoice_uses_custom_logic(self):
        """
        Test: Multi-currency JE from Service Invoice should use custom logic.
        Expected: Keep company amounts, recalculate account currency amounts.
        """
        # Mock frappe.db.exists to return True for Service Invoice
        self.mock_frappe_db.exists.return_value = True
        
        # Create multi-currency JE with cheque_no pointing to Service Invoice
        je = self.create_mock_je(multi_currency=True, cheque_no="SINV-001")
        
        # Add a row with company amounts already set (like from JournalEntryBuilder)
        row = self.add_account_row(
            je,
            debit=120.0,  # Company amount already set
            debit_in_account_currency=0,  # Account currency amount to be recalculated
            exchange_rate=1.2
        )
        
        # Call the method
        je.set_amounts_in_company_currency()
        
        # Verify custom logic: debit_in_account_currency = debit / exchange_rate = 120.0 / 1.2 = 100.0
        self.assertEqual(flt(row.debit), 120.0)  # Company amount unchanged
        self.assertEqual(flt(row.debit_in_account_currency), 100.0)  # Recalculated
        
        # Verify frappe.db.exists was called correctly
        self.mock_frappe_db.exists.assert_called_once_with("Service Invoice", "SINV-001")
    
    def test_multi_currency_je_with_cheque_no_but_not_service_invoice(self):
        """
        Test: Multi-currency JE with cheque_no but not a Service Invoice uses standard behavior.
        Expected: debit = debit_in_account_currency × exchange_rate
        """
        # Mock frappe.db.exists to return False (not a Service Invoice)
        self.mock_frappe_db.exists.return_value = False
        
        # Create multi-currency JE with cheque_no that doesn't exist as Service Invoice
        je = self.create_mock_je(multi_currency=True, cheque_no="SOME-OTHER-DOC")
        
        # Add a row with account currency amounts only
        row = self.add_account_row(
            je,
            debit=0,  # Company amount not set
            debit_in_account_currency=100.0,
            exchange_rate=1.2
        )
        
        # Call the method
        je.set_amounts_in_company_currency()
        
        # Verify standard behavior: debit = 100.0 × 1.2 = 120.0
        self.assertEqual(flt(row.debit), 120.0)
        self.assertEqual(flt(row.debit_in_account_currency), 100.0)
    
    def test_credit_amounts_follow_same_logic(self):
        """
        Test: Credit amounts follow the same logic as debit amounts.
        """
        # Mock frappe.db.exists to return True for Service Invoice
        self.mock_frappe_db.exists.return_value = True
        
        # Create multi-currency JE from Service Invoice
        je = self.create_mock_je(multi_currency=True, cheque_no="SINV-002")
        
        # Add a row with company credit already set
        row = self.add_account_row(
            je,
            credit=240.0,  # Company amount already set
            credit_in_account_currency=0,  # To be recalculated
            exchange_rate=2.0
        )
        
        # Call the method
        je.set_amounts_in_company_currency()
        
        # Verify custom logic: credit_in_account_currency = credit / exchange_rate = 240.0 / 2.0 = 120.0
        self.assertEqual(flt(row.credit), 240.0)  # Company amount unchanged
        self.assertEqual(flt(row.credit_in_account_currency), 120.0)  # Recalculated
    
    def test_exchange_gain_or_loss_je_skipped(self):
        """
        Test: Exchange Gain Or Loss JE should be skipped.
        """
        # Create Exchange Gain Or Loss JE
        je = self.create_mock_je(
            multi_currency=True, 
            voucher_type="Exchange Gain Or Loss"
        )
        
        # Add a row
        row = self.add_account_row(
            je,
            debit=100.0,
            debit_in_account_currency=100.0,
            exchange_rate=1.0
        )
        
        # Store original values
        original_debit = row.debit
        original_debit_in_account_currency = row.debit_in_account_currency
        
        # Call the method
        je.set_amounts_in_company_currency()
        
        # Verify nothing changed (method returns early for Exchange Gain Or Loss)
        self.assertEqual(row.debit, original_debit)
        self.assertEqual(row.debit_in_account_currency, original_debit_in_account_currency)
    
    def test_multiple_rows_mixed_scenarios(self):
        """
        Test: Multiple rows in a JE from Service Invoice all use custom logic.
        """
        # Mock frappe.db.exists to return True for Service Invoice
        self.mock_frappe_db.exists.return_value = True
        
        # Create multi-currency JE from Service Invoice
        je = self.create_mock_je(multi_currency=True, cheque_no="SINV-003")
        
        # Add multiple rows with company amounts set
        row1 = self.add_account_row(
            je,
            debit=150.0,  # Company amount set
            exchange_rate=1.5
        )
        
        row2 = self.add_account_row(
            je,
            credit=150.0,  # Company amount set
            exchange_rate=1.5
        )
        
        # Call the method
        je.set_amounts_in_company_currency()
        
        # Verify both rows use custom logic
        self.assertEqual(flt(row1.debit), 150.0)
        self.assertEqual(flt(row1.debit_in_account_currency), 100.0)  # 150.0 / 1.5
        
        self.assertEqual(flt(row2.credit), 150.0)
        self.assertEqual(flt(row2.credit_in_account_currency), 100.0)  # 150.0 / 1.5


if __name__ == '__main__':
    unittest.main()
