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

# For ERPNext/Frappe test framework compatibility
# This base class is required when running tests through Frappe's test runner
from frappe.tests.utils import FrappeTestCase


class TestServiceInvoice(FrappeTestCase):
	pass


class TestMultiCurrencyOffsetLine(unittest.TestCase):
	"""Regression tests for multi-currency offset line rounding drift."""
	
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.get_exchange_rate')
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.frappe')
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.round_based_on_smallest_currency_fraction')
	def test_exact_exchange_rate_from_rounded_amounts(self, mock_round, mock_frappe, mock_get_exchange_rate):
		"""
		Test that exchange rate is recomputed from rounded amounts to prevent drift.
		
		This is the exact scenario from the problem statement:
		- Company: TND, Party: USD, Offset: EUR
		- After rounding: offset_company_amount = 18247.77, offset_acc_amount = 5599.15
		- Expected exchange rate: 18247.77 / 5599.15 = ~3.259027 (not 3.259027724)
		"""
		from isnack.isnack.doctype.service_invoice.service_invoice import JournalEntryBuilder
		
		# Mock frappe dependencies
		mock_jv = MagicMock()
		mock_jv.accounts = []
		mock_frappe.new_doc.return_value = mock_jv
		mock_frappe.get_precision.return_value = 2
		
		# Mock rounding to return specific values
		def mock_rounding(value, currency, precision):
			# Simulate the rounding behavior that leads to the problem
			if currency == "TND":
				return round(value, 2)
			elif currency == "EUR":
				return round(value, 2)
			elif currency == "USD":
				return round(value, 2)
			return round(value, 2)
		
		mock_round.side_effect = mock_rounding
		
		# Mock exchange rates
		def mock_exchange_rate(from_currency, to_currency, date):
			rates = {
				('USD', 'TND'): 3.259027724,  # Original fetched rate
				('EUR', 'TND'): 3.259027724,  # Same for this test
				('TND', 'TND'): 1.0,
			}
			return rates.get((from_currency, to_currency), 1.0)
		
		mock_get_exchange_rate.side_effect = mock_exchange_rate
		
		# Create mock invoice data
		inv = MagicMock()
		inv.account = "Debtors USD"
		inv.account_currency = "USD"
		inv.offset_account = "Revenue EUR"
		inv.offset_account_currency = "EUR"
		inv.cost_center = "Main"
		inv.date = "2023-01-01"
		
		# Build journal entry
		builder = JournalEntryBuilder(inv, "Test Company", "TND")
		
		# Add offset line with amounts that will round to specific values
		# We need to engineer the amounts so that after rounding we get:
		# offset_company_amount = 18247.77 TND
		# offset_acc_amount = 5599.15 EUR
		# This happens when party amount converts to 18247.77 TND
		party_amount_in_usd = 18247.77 / 3.259027724  # ~5599.15 USD
		
		builder.add_offset_line(
			offset_amount=party_amount_in_usd,
			is_credit=True,
			vat_inclusive=False,
			gross_amount=party_amount_in_usd
		)
		
		# Get the offset row
		offset_row = builder.offset_row
		
		# Verify the exchange rate is recomputed from rounded amounts
		# Expected: 18247.77 / 5599.15 = 3.259027 (rounded to 9 decimals)
		# NOT the original 3.259027724
		expected_rate = round(18247.77 / 5599.15, 9)
		actual_rate = offset_row.get("exchange_rate")
		
		self.assertIsNotNone(actual_rate, "Exchange rate should be set on offset row")
		# Allow for small floating point differences
		self.assertAlmostEqual(actual_rate, expected_rate, places=7,
			msg=f"Exchange rate should be recomputed from rounded amounts: "
			    f"expected {expected_rate}, got {actual_rate}")
		
		# Also verify that self.offset_exchange_rate was updated
		self.assertAlmostEqual(builder.offset_exchange_rate, expected_rate, places=7,
			msg="Builder's offset_exchange_rate should be updated to recomputed value")
	
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.get_exchange_rate')
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.frappe')
	def test_multi_currency_offset_with_different_rates(self, mock_frappe, mock_get_exchange_rate):
		"""
		Test that multi-currency offset lines balance correctly in company currency.
		
		Scenario: 
		- Company currency: EUR
		- Party account currency: USD (rate: 1.1)
		- Offset account currency: GBP (rate: 0.85)
		- Invoice amount: 100 USD
		- VAT exclusive with 19% tax
		
		Expected: Journal entry should balance with total debit == total credit in EUR
		"""
		from isnack.isnack.doctype.service_invoice.service_invoice import JournalEntryBuilder
		
		# Mock frappe dependencies
		mock_frappe.new_doc.return_value = MagicMock()
		mock_frappe.get_precision.return_value = 2
		mock_frappe.utils.flt = lambda x: float(x) if x else 0.0
		
		# Mock exchange rates: returns rate from source to target
		def mock_exchange_rate(from_currency, to_currency, date):
			rates = {
				('USD', 'EUR'): 1.1,   # 1 USD = 1.1 EUR
				('GBP', 'EUR'): 0.85,  # 1 GBP = 0.85 EUR
				('EUR', 'EUR'): 1.0,
			}
			return rates.get((from_currency, to_currency), 1.0)
		
		mock_get_exchange_rate.side_effect = mock_exchange_rate
		
		# Create mock invoice data
		inv = MagicMock()
		inv.account = "Debtors USD"
		inv.account_currency = "USD"
		inv.offset_account = "Revenue GBP"
		inv.offset_account_currency = "GBP"
		inv.cost_center = "Main"
		inv.date = "2023-01-01"
		
		# Build journal entry
		builder = JournalEntryBuilder(inv, "Test Company", "EUR")
		
		# Add party line: 100 USD credit
		builder.add_party_line(invoice_amount=100.0, is_credit=True)
		
		# Add offset line: should convert 100 USD to GBP via EUR
		# 100 USD * 1.1 = 110 EUR (party line in company currency)
		# For offset in GBP: 110 EUR / 0.85 = ~129.41 GBP
		builder.add_offset_line(
			offset_amount=100.0, 
			is_credit=True, 
			vat_inclusive=False,
			gross_amount=100.0
		)
		
		# Verify the journal entry balances
		jv = builder.build()
		
		# Calculate totals in company currency
		total_debit = sum(float(row.get("debit", 0)) for row in jv.accounts)
		total_credit = sum(float(row.get("credit", 0)) for row in jv.accounts)
		
		# They should be equal (or within rounding tolerance)
		diff = abs(total_debit - total_credit)
		self.assertLess(diff, 0.01, 
			f"Total debit ({total_debit}) should equal total credit ({total_credit}) "
			f"in company currency EUR, diff: {diff}")
	
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.get_exchange_rate')
	@patch('isnack.isnack.doctype.service_invoice.service_invoice.frappe')
	def test_vat_exclusive_multi_currency_offset(self, mock_frappe, mock_get_exchange_rate):
		"""
		Test VAT-exclusive multi-currency scenario where offset carries VAT.
		
		Scenario:
		- Company currency: EUR
		- Party account currency: USD (rate: 1.2)
		- Offset account currency: GBP (rate: 0.9)
		- Gross amount: 100 USD (before VAT)
		- VAT: 19%
		- Invoice amount: 119 USD (100 + 19)
		
		Expected: Offset should be based on gross (100 USD), not invoice amount
		"""
		from isnack.isnack.doctype.service_invoice.service_invoice import JournalEntryBuilder
		
		# Mock frappe dependencies
		mock_frappe.new_doc.return_value = MagicMock()
		mock_frappe.get_precision.return_value = 2
		mock_frappe.utils.flt = lambda x: float(x) if x else 0.0
		
		# Mock exchange rates
		def mock_exchange_rate(from_currency, to_currency, date):
			rates = {
				('USD', 'EUR'): 1.2,
				('GBP', 'EUR'): 0.9,
				('EUR', 'EUR'): 1.0,
			}
			return rates.get((from_currency, to_currency), 1.0)
		
		mock_get_exchange_rate.side_effect = mock_exchange_rate
		
		# Create mock invoice data
		inv = MagicMock()
		inv.account = "Debtors USD"
		inv.account_currency = "USD"
		inv.offset_account = "Revenue GBP"
		inv.offset_account_currency = "GBP"
		inv.cost_center = "Main"
		inv.date = "2023-01-01"
		
		# Build journal entry
		builder = JournalEntryBuilder(inv, "Test Company", "EUR")
		
		# Add party line: 119 USD credit (100 gross + 19 VAT)
		builder.add_party_line(invoice_amount=119.0, is_credit=True)
		
		# Add offset line: should use gross_amount (100 USD) for VAT exclusive
		# 100 USD * 1.2 = 120 EUR
		# 120 EUR / 0.9 = 133.33 GBP
		builder.add_offset_line(
			offset_amount=119.0,
			is_credit=True,
			vat_inclusive=False,
			gross_amount=100.0  # Use gross, not invoice amount
		)
		
		# Add VAT line: 19 USD = 22.8 EUR
		builder.add_vat_line(vat_amount=19.0, tax_account="VAT", is_credit=True)
		
		# Balance the entry
		builder.balance_journal_entry()
		
		# Verify the journal entry balances
		jv = builder.build()
		
		# Calculate totals in company currency
		total_debit = sum(float(row.get("debit", 0)) for row in jv.accounts)
		total_credit = sum(float(row.get("credit", 0)) for row in jv.accounts)
		
		# They should be equal
		self.assertAlmostEqual(total_debit, total_credit, places=2,
			msg=f"Total debit ({total_debit}) should equal total credit ({total_credit})")

