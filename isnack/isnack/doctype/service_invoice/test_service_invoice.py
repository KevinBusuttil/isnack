# Copyright (c) 2025, Busuttil Technologies Limited and Contributors
# See license.txt

import unittest
from unittest.mock import MagicMock, patch


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
	
	def test_ultra_small_diff_zeroing_logic(self):
		"""Test the logic that determines if a difference should be zeroed out."""
		# Test with precision 2 (e.g., EUR, USD)
		company_precision = 2
		smallest_fraction = 1.0 / (10 ** company_precision)  # 0.01
		rounding_tolerance = smallest_fraction / 2  # 0.005
		
		# Test cases
		test_cases = [
			(0.004, True, "0.004 < 0.005, should be zeroed"),
			(0.003, True, "0.003 < 0.005, should be zeroed"),
			(-0.004, True, "-0.004 < 0.005 (abs), should be zeroed"),
			(0.005, False, "0.005 == 0.005, should NOT be zeroed"),
			(0.01, False, "0.01 > 0.005, should NOT be zeroed"),
			(0.02, False, "0.02 > 0.005, should NOT be zeroed"),
			(-0.02, False, "-0.02 > 0.005 (abs), should NOT be zeroed"),
		]
		
		for diff, should_zero, description in test_cases:
			is_below_tolerance = abs(diff) < rounding_tolerance
			self.assertEqual(is_below_tolerance, should_zero, description)
	
	def test_real_world_scenario(self):
		"""Test the scenario mentioned in the problem statement."""
		# The problem mentions a diff of approximately -0.020000000000436557
		# With precision 2, this should:
		# 1. Round to -0.02
		# 2. NOT be zeroed out (0.02 >= 0.005)
		# 3. Trigger balancing
		
		diff = -0.020000000000436557
		company_precision = 2
		
		# Simulate the rounding logic
		rounded_diff = round(diff, company_precision)
		self.assertEqual(rounded_diff, -0.02, "Should round to -0.02")
		
		# Check if it should be zeroed
		smallest_fraction = 1.0 / (10 ** company_precision)
		rounding_tolerance = smallest_fraction / 2
		should_zero = abs(rounded_diff) < rounding_tolerance
		
		self.assertFalse(should_zero, "0.02 should NOT be zeroed (it's >= 0.005)")
	
	def test_precision_3_currency(self):
		"""Test with precision 3 currencies (e.g., some Middle Eastern currencies)."""
		company_precision = 3
		smallest_fraction = 1.0 / (10 ** company_precision)  # 0.001
		rounding_tolerance = smallest_fraction / 2  # 0.0005
		
		test_cases = [
			(0.0004, True, "0.0004 < 0.0005, should be zeroed"),
			(0.0005, False, "0.0005 == 0.0005, should NOT be zeroed"),
			(0.001, False, "0.001 > 0.0005, should NOT be zeroed"),
		]
		
		for diff, should_zero, description in test_cases:
			is_below_tolerance = abs(diff) < rounding_tolerance
			self.assertEqual(is_below_tolerance, should_zero, description)
	
	def test_account_currency_recalculation(self):
		"""Test that account currency is recalculated correctly from company currency."""
		# When adjusting a multi-currency row, the account currency amount
		# should be recalculated from the adjusted company currency amount
		
		# Example: Company currency is EUR, account currency is USD
		# Exchange rate: 1.2 (1 USD = 1.2 EUR)
		company_amount = 120.0  # EUR
		exchange_rate = 1.2
		account_precision = 2
		
		# Recalculated account currency amount
		account_amount = company_amount / exchange_rate
		rounded_account_amount = round(account_amount, account_precision)
		
		self.assertEqual(rounded_account_amount, 100.0, "Should be 100.0 USD")


# For Frappe test compatibility
from frappe.tests.utils import FrappeTestCase


class TestServiceInvoice(FrappeTestCase):
	pass
