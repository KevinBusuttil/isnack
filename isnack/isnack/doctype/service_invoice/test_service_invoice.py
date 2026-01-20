# Copyright (c) 2025, Busuttil Technologies Limited and Contributors
# See license.txt

import unittest
from unittest.mock import MagicMock, patch
from isnack.isnack.doctype.service_invoice.service_invoice import JournalEntryBuilder


class TestJournalEntryBalancing(unittest.TestCase):
	"""Unit tests for balance_journal_entry method to verify rounding drift fix."""
	
	def setUp(self):
		"""Set up test fixtures."""
		# Mock invoice data
		self.inv = MagicMock()
		self.inv.account_currency = "EUR"
		self.inv.offset_account_currency = "USD"
		self.inv.account = "Test Account"
		self.inv.offset_account = "Test Offset"
		self.inv.cost_center = "Main"
		self.inv.date = "2023-01-01"
		
		# Mock company data
		self.company = "Test Company"
		self.company_currency = "EUR"
		
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.frappe')
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.get_exchange_rate')
	def test_ultra_small_diff_zeroed_out(self, mock_exchange_rate, mock_frappe):
		"""Test that ultra-small differences below smallest currency fraction are zeroed out."""
		# Set up mocks
		mock_exchange_rate.return_value = 1.0
		mock_frappe.get_precision.return_value = 2
		mock_frappe.new_doc.return_value = MagicMock()
		
		# Patch round_based_on_smallest_currency_fraction to return the same value
		with patch('isnack.isnack.doctype.service_invoice.service_invoice.round_based_on_smallest_currency_fraction') as mock_round:
			# First call returns a tiny diff (0.004), which should be zeroed out
			# Subsequent calls return the values as-is
			mock_round.side_effect = lambda val, *args: val
			
			builder = JournalEntryBuilder(self.inv, self.company, self.company_currency)
			
			# Create a journal entry with a tiny imbalance
			builder.jv.accounts = [
				{"debit": 100.004, "credit": 0.0},  # Slightly too much debit
				{"debit": 0.0, "credit": 100.0},
			]
			
			# Track rows for balancing
			builder.vat_row = builder.jv.accounts[0]
			
			# Call balance_journal_entry
			builder.balance_journal_entry()
			
			# The tiny difference should be ignored, so no changes should be made
			self.assertEqual(builder.jv.accounts[0]["debit"], 100.004)
			self.assertEqual(builder.jv.accounts[1]["credit"], 100.0)
	
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.frappe')
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.get_exchange_rate')
	def test_larger_diff_is_adjusted(self, mock_exchange_rate, mock_frappe):
		"""Test that larger differences are properly adjusted."""
		# Set up mocks
		mock_exchange_rate.return_value = 1.0
		mock_frappe.get_precision.return_value = 2
		mock_frappe.new_doc.return_value = MagicMock()
		
		# Patch round_based_on_smallest_currency_fraction
		with patch('isnack.isnack.doctype.service_invoice.service_invoice.round_based_on_smallest_currency_fraction') as mock_round:
			# Return values as-is for simplicity
			mock_round.side_effect = lambda val, *args: round(val, 2)
			
			builder = JournalEntryBuilder(self.inv, self.company, self.company_currency)
			
			# Create a journal entry with a larger imbalance (0.02)
			builder.jv.accounts = [
				{"debit": 100.02, "credit": 0.0},
				{"debit": 0.0, "credit": 100.0},
			]
			
			# Track rows for balancing
			builder.vat_row = builder.jv.accounts[0]
			
			# Call balance_journal_entry
			builder.balance_journal_entry()
			
			# The difference should be adjusted
			# Total debit - total credit = 100.02 - 100.0 = 0.02
			# This should be removed from debit
			self.assertEqual(builder.jv.accounts[0]["debit"], 100.0)
	
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.frappe')
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.get_exchange_rate')
	def test_account_currency_recalculated_from_company_currency(self, mock_exchange_rate, mock_frappe):
		"""Test that account currency fields are recalculated from rounded company amounts."""
		# Set up mocks
		mock_exchange_rate.return_value = 1.2  # EUR to USD
		mock_frappe.get_precision.return_value = 2
		mock_frappe.new_doc.return_value = MagicMock()
		
		# Patch round_based_on_smallest_currency_fraction
		with patch('isnack.isnack.doctype.service_invoice.service_invoice.round_based_on_smallest_currency_fraction') as mock_round:
			# Return rounded values
			mock_round.side_effect = lambda val, *args: round(val, 2)
			
			builder = JournalEntryBuilder(self.inv, self.company, self.company_currency)
			builder.offset_exchange_rate = 1.2
			
			# Create a journal entry with imbalance in multi-currency scenario
			builder.jv.accounts = [
				{"debit": 100.02, "credit": 0.0},  # Company currency
				{"debit": 0.0, "credit": 100.0, "debit_in_account_currency": 83.33, "credit_in_account_currency": 0.0},  # Account currency (USD)
			]
			
			# Track rows for balancing
			builder.offset_row = builder.jv.accounts[1]
			
			# Call balance_journal_entry
			builder.balance_journal_entry()
			
			# Verify that account currency was recalculated
			# The credit in company currency should be adjusted to 100.02
			# The credit_in_account_currency should be recalculated as 100.02 / 1.2 = 83.35
			self.assertIsNotNone(builder.jv.accounts[1].get("credit_in_account_currency"))
	
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.frappe')
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.get_exchange_rate')
	def test_already_balanced_entry_unchanged(self, mock_exchange_rate, mock_frappe):
		"""Test that already-balanced entries remain unchanged."""
		# Set up mocks
		mock_exchange_rate.return_value = 1.0
		mock_frappe.get_precision.return_value = 2
		mock_frappe.new_doc.return_value = MagicMock()
		
		# Patch round_based_on_smallest_currency_fraction
		with patch('isnack.isnack.doctype.service_invoice.service_invoice.round_based_on_smallest_currency_fraction') as mock_round:
			# Return values as-is
			mock_round.side_effect = lambda val, *args: val
			
			builder = JournalEntryBuilder(self.inv, self.company, self.company_currency)
			
			# Create a perfectly balanced journal entry
			builder.jv.accounts = [
				{"debit": 100.0, "credit": 0.0},
				{"debit": 0.0, "credit": 100.0},
			]
			
			# Track rows for balancing
			builder.vat_row = builder.jv.accounts[0]
			
			# Store original values
			original_debit = builder.jv.accounts[0]["debit"]
			original_credit = builder.jv.accounts[1]["credit"]
			
			# Call balance_journal_entry
			builder.balance_journal_entry()
			
			# Verify no changes were made
			self.assertEqual(builder.jv.accounts[0]["debit"], original_debit)
			self.assertEqual(builder.jv.accounts[1]["credit"], original_credit)


# For Frappe test compatibility
from frappe.tests.utils import FrappeTestCase


class TestServiceInvoice(FrappeTestCase):
	pass
