# Copyright (c) 2025, Busuttil Technologies Limited
# License: MIT
"""
Tests for the configurable withholding basis (custom_deduct_tax_on_basis).

These tests verify:
1. The helper functions in ``isnack.overrides.tax_withholding``.
2. Purchase Invoice – net vs gross withholding amounts.
3. Payment Entry – net vs gross via CustomPaymentEntry.
4. Journal Entry – net vs gross via CustomJournalEntry.
5. Backward compatibility (Net Total default).

All ERPNext / Frappe DB calls are mocked so that these tests run standalone
(without a live Frappe/ERPNext installation).
"""

import sys
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Bootstrap: stub out Frappe / ERPNext modules before any isnack imports
# ---------------------------------------------------------------------------


class _FrappeDict(dict):
    """Minimal stand-in for frappe._dict."""

    def __getattr__(self, key):
        return self.get(key)

    def __setattr__(self, key, value):
        self[key] = value

    def get(self, key, default=None):
        return super().get(key, default)


def _flt(value, precision=None):
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _patch_sys_modules():
    """Inject stub modules so isnack modules can be imported without ERPNext."""
    _twc_stub = MagicMock()
    _twc_stub.get_tds_amount = MagicMock(return_value=0.0)

    stubs = {
        "frappe": MagicMock(_dict=_FrappeDict, utils=MagicMock(flt=_flt)),
        "frappe.utils": MagicMock(flt=_flt),
        "frappe.model": MagicMock(),
        "frappe.model.document": MagicMock(),
        "erpnext": MagicMock(),
        "erpnext.accounts": MagicMock(),
        "erpnext.accounts.report": MagicMock(),
        "erpnext.accounts.report.utils": MagicMock(),
        "erpnext.accounts.doctype": MagicMock(),
        "erpnext.accounts.doctype.tax_withholding_category": MagicMock(),
        "erpnext.accounts.doctype.tax_withholding_category.tax_withholding_category": _twc_stub,
        "erpnext.accounts.doctype.payment_entry": MagicMock(),
        "erpnext.accounts.doctype.payment_entry.payment_entry": MagicMock(),
        "erpnext.accounts.doctype.journal_entry": MagicMock(),
        "erpnext.accounts.doctype.journal_entry.journal_entry": MagicMock(),
        "erpnext.controllers": MagicMock(),
        "erpnext.controllers.accounts_controller": MagicMock(),
    }

    for mod_name, stub in stubs.items():
        if mod_name not in sys.modules:
            sys.modules[mod_name] = stub

    # frappe._dict must be accessible as frappe._dict
    sys.modules["frappe"]._dict = _FrappeDict
    sys.modules["frappe"].db = MagicMock()

    return _twc_stub


_twc_stub = _patch_sys_modules()

# Only import isnack modules AFTER the stubs are in place to avoid
# the "No module named 'erpnext'" error.
# The isnack __init__ applies the monkey-patch as a side-effect.
import isnack  # noqa: E402  (must be after stub setup)
from isnack.overrides import tax_withholding as _tw_mod  # noqa: E402

# Convenience alias for frappe._dict used in tests
_fdict = _FrappeDict


def _dict(**kw):
    return _fdict(kw)


# ---------------------------------------------------------------------------
# 1. Helper function unit tests
# ---------------------------------------------------------------------------


class TestGetDeductTaxOnBasis(unittest.TestCase):
    """Tests for ``get_deduct_tax_on_basis``."""

    def setUp(self):
        self.patcher = patch(
            "isnack.overrides.tax_withholding.frappe.db.get_value"
        )
        self.mock_get_value = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_returns_net_total_when_category_is_none(self):
        from isnack.overrides.tax_withholding import get_deduct_tax_on_basis

        result = get_deduct_tax_on_basis(None)
        self.assertEqual(result, "Net Total")
        self.mock_get_value.assert_not_called()

    def test_returns_net_total_when_field_is_empty(self):
        from isnack.overrides.tax_withholding import get_deduct_tax_on_basis

        self.mock_get_value.return_value = ""
        result = get_deduct_tax_on_basis("TDS-5%")
        self.assertEqual(result, "Net Total")

    def test_returns_stored_value_when_set_to_gross(self):
        from isnack.overrides.tax_withholding import get_deduct_tax_on_basis

        self.mock_get_value.return_value = "Gross Total"
        result = get_deduct_tax_on_basis("TDS-TN")
        self.assertEqual(result, "Gross Total")

    def test_returns_stored_value_when_set_to_net(self):
        from isnack.overrides.tax_withholding import get_deduct_tax_on_basis

        self.mock_get_value.return_value = "Net Total"
        result = get_deduct_tax_on_basis("TDS-5%")
        self.assertEqual(result, "Net Total")

    def test_returns_net_total_on_exception(self):
        from isnack.overrides.tax_withholding import get_deduct_tax_on_basis

        self.mock_get_value.side_effect = Exception("DB error")
        result = get_deduct_tax_on_basis("TDS-5%")
        self.assertEqual(result, "Net Total")

    def test_default_is_net_total_for_new_field(self):
        """Regression: existing records without the field return Net Total."""
        from isnack.overrides.tax_withholding import get_deduct_tax_on_basis

        self.mock_get_value.return_value = None
        result = get_deduct_tax_on_basis("OLD-TDS")
        self.assertEqual(result, "Net Total")


class TestIsGrossBasisEnabled(unittest.TestCase):
    """Tests for ``is_gross_basis_enabled``."""

    def setUp(self):
        self.patcher = patch(
            "isnack.overrides.tax_withholding.frappe.db.get_value"
        )
        self.mock_get_value = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_returns_false_for_net_total(self):
        from isnack.overrides.tax_withholding import is_gross_basis_enabled

        self.mock_get_value.return_value = "Net Total"
        self.assertFalse(is_gross_basis_enabled("TDS-5%"))

    def test_returns_true_for_gross_total(self):
        from isnack.overrides.tax_withholding import is_gross_basis_enabled

        self.mock_get_value.return_value = "Gross Total"
        self.assertTrue(is_gross_basis_enabled("TDS-TN"))

    def test_returns_false_when_category_is_none(self):
        from isnack.overrides.tax_withholding import is_gross_basis_enabled

        self.assertFalse(is_gross_basis_enabled(None))


# ---------------------------------------------------------------------------
# 2. Purchase Invoice – patched get_tds_amount
# ---------------------------------------------------------------------------


class TestPurchaseInvoiceWithholding(unittest.TestCase):
    """
    Test that the monkey-patched ``get_tds_amount`` correctly uses gross basis
    for Purchase Invoice when ``custom_deduct_tax_on_basis == "Gross Total"``.

    Scenario:
        net = 1000, VAT = 190 (19%), gross/TTC = 1190, rate = 1.5%
        Net Total mode  → expected = 15.00
        Gross Total mode → expected = 17.85
    """

    NET = 1000.0
    GROSS = 1190.0
    RATE = 1.5

    def _make_pi_inv(self):
        """Minimal Purchase Invoice dict consumed by get_tds_amount."""
        return _dict(
            doctype="Purchase Invoice",
            tax_withholding_net_total=self.NET,
            base_tax_withholding_net_total=self.NET,
            grand_total=self.GROSS,
            base_grand_total=self.GROSS,
        )

    def _make_tax_details(self, category="TDS-TN"):
        return _dict(
            tax_withholding_category=category,
            rate=self.RATE,
            threshold=0,
            cumulative_threshold=0,
            consider_party_ledger_amount=0,
            tax_on_excess_amount=0,
        )

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_net_total_mode_uses_net_basis(self, mock_get_value):
        """Net Total mode: withholding = NET × rate = 1000 × 1.5% = 15."""
        from isnack.overrides.tax_withholding import _patched_get_tds_amount

        mock_get_value.return_value = "Net Total"

        inv = self._make_pi_inv()
        tax_details = self._make_tax_details()

        # The original get_tds_amount is called with inv.tax_withholding_net_total
        # unchanged (= NET = 1000).  We mock it to return NET * rate.
        with patch(
            "isnack.overrides.tax_withholding._original_get_tds_amount",
            side_effect=lambda ldc, parties, inv, td, vwa: inv.get("tax_withholding_net_total") * td.rate / 100,
        ):
            result = _patched_get_tds_amount(None, [], inv, tax_details, [])

        self.assertAlmostEqual(result, 15.0, places=2)
        # Originals must be restored
        self.assertEqual(inv.tax_withholding_net_total, self.NET)
        self.assertEqual(inv.base_tax_withholding_net_total, self.NET)

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_gross_total_mode_uses_gross_basis(self, mock_get_value):
        """Gross Total mode: withholding = GROSS × rate = 1190 × 1.5% = 17.85."""
        from isnack.overrides.tax_withholding import _patched_get_tds_amount

        mock_get_value.return_value = "Gross Total"

        inv = self._make_pi_inv()
        tax_details = self._make_tax_details()

        captured = {}

        def _fake_original(ldc, parties, inv, td, vwa):
            captured["tax_withholding_net_total"] = inv.get("tax_withholding_net_total")
            return inv.get("tax_withholding_net_total") * td.rate / 100

        with patch(
            "isnack.overrides.tax_withholding._original_get_tds_amount",
            side_effect=_fake_original,
        ):
            result = _patched_get_tds_amount(None, [], inv, tax_details, [])

        # The gross value should have been used inside the original call
        self.assertAlmostEqual(captured["tax_withholding_net_total"], self.GROSS, places=2)
        self.assertAlmostEqual(result, 17.85, places=2)
        # Originals must be restored after the call
        self.assertEqual(inv.tax_withholding_net_total, self.NET)
        self.assertEqual(inv.base_tax_withholding_net_total, self.NET)

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_originals_restored_on_exception(self, mock_get_value):
        """Even when the original raises, inv values must be restored."""
        from isnack.overrides.tax_withholding import _patched_get_tds_amount

        mock_get_value.return_value = "Gross Total"
        inv = self._make_pi_inv()
        tax_details = self._make_tax_details()

        with patch(
            "isnack.overrides.tax_withholding._original_get_tds_amount",
            side_effect=Exception("DB failure"),
        ):
            with self.assertRaises(Exception):
                _patched_get_tds_amount(None, [], inv, tax_details, [])

        self.assertEqual(inv.tax_withholding_net_total, self.NET)
        self.assertEqual(inv.base_tax_withholding_net_total, self.NET)


# ---------------------------------------------------------------------------
# 3. Payment Entry – CustomPaymentEntry
# ---------------------------------------------------------------------------


class TestCustomPaymentEntry(unittest.TestCase):
    """Tests for ``CustomPaymentEntry.calculate_tax_withholding_net_total``."""

    NET = 1000.0
    GROSS = 1190.0

    def _make_pe(self, allocated=1190.0, outstanding=1190.0, unallocated=0.0):
        """Minimal Payment Entry mock."""
        from isnack.overrides.payment_entry import CustomPaymentEntry

        pe = CustomPaymentEntry.__new__(CustomPaymentEntry)
        pe.tax_withholding_category = "TDS-TN"
        pe.unallocated_amount = unallocated

        ref = _dict(
            allocated_amount=allocated,
            outstanding_amount=outstanding,
        )
        pe.references = [ref]
        return pe

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_net_total_mode_delegates_to_parent(self, mock_get_value):
        """Net Total mode must call super().calculate_tax_withholding_net_total()."""
        from isnack.overrides.payment_entry import CustomPaymentEntry

        mock_get_value.return_value = "Net Total"
        pe = self._make_pe()

        with patch.object(
            CustomPaymentEntry.__bases__[0],
            "calculate_tax_withholding_net_total",
            return_value=self.NET,
        ) as mock_super:
            result = pe.calculate_tax_withholding_net_total()

        mock_super.assert_called_once()
        self.assertEqual(result, self.NET)

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_gross_total_mode_returns_gross(self, mock_get_value):
        """Gross Total mode: returns sum of allocated amounts (gross TTC)."""
        mock_get_value.return_value = "Gross Total"
        pe = self._make_pe(allocated=self.GROSS, outstanding=self.GROSS)

        result = pe.calculate_tax_withholding_net_total()
        self.assertAlmostEqual(result, self.GROSS, places=2)

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_gross_total_with_unallocated_amount(self, mock_get_value):
        """Gross mode: unallocated_amount is added to the gross basis."""
        mock_get_value.return_value = "Gross Total"
        pe = self._make_pe(allocated=500.0, outstanding=500.0, unallocated=200.0)

        result = pe.calculate_tax_withholding_net_total()
        self.assertAlmostEqual(result, 700.0, places=2)

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_gross_total_capped_at_outstanding(self, mock_get_value):
        """Gross mode: allocated is capped at outstanding when over-allocated."""
        mock_get_value.return_value = "Gross Total"
        pe = self._make_pe(allocated=2000.0, outstanding=1190.0, unallocated=0.0)

        result = pe.calculate_tax_withholding_net_total()
        self.assertAlmostEqual(result, 1190.0, places=2)


# ---------------------------------------------------------------------------
# 4. Journal Entry – _GrossJournalEntryTaxWithholding and CustomJournalEntry
# ---------------------------------------------------------------------------


class TestGrossJournalEntryTaxWithholding(unittest.TestCase):
    """Tests for ``_GrossJournalEntryTaxWithholding._calculate_net_total``."""

    def _make_je_handler(self, accounts, party_account="Supplier-AP", precision=2):
        """Build a minimal JournalEntryTaxWithholding-like handler."""
        from isnack.overrides.journal_entry import _GrossJournalEntryTaxWithholding

        doc = MagicMock()
        doc.get.return_value = accounts
        doc.company = "Test Company"

        handler = _GrossJournalEntryTaxWithholding.__new__(
            _GrossJournalEntryTaxWithholding
        )
        handler.doc = doc
        handler.party_account = party_account
        handler.party_field = "credit"
        handler.reverse_field = "debit"
        handler.precision = precision
        return handler

    def test_includes_tax_accounts_in_gross(self):
        """Gross total includes Tax account rows that the net method excludes."""
        from isnack.overrides.journal_entry import _GrossJournalEntryTaxWithholding

        # Expense row: debit=1000
        expense_row = _dict(account="Expense-ACC", debit=1000.0, credit=0.0,
                            is_tax_withholding_account=0)
        # VAT tax row: debit=190
        tax_row = _dict(account="VAT-ACC", debit=190.0, credit=0.0,
                        is_tax_withholding_account=0)
        # Supplier row: credit=1190 (party account – excluded)
        supplier_row = _dict(account="Supplier-AP", debit=0.0, credit=1190.0,
                             is_tax_withholding_account=0)

        handler = self._make_je_handler(
            accounts=[expense_row, tax_row, supplier_row],
            party_account="Supplier-AP",
        )
        # Override doc.get to return the accounts list
        handler.doc.get = lambda key: [expense_row, tax_row, supplier_row]

        result = handler._calculate_net_total()
        # Gross = expense(1000) + tax(190) = 1190
        self.assertAlmostEqual(result, 1190.0, places=2)

    def test_excludes_tds_row_from_gross(self):
        """TDS rows (is_tax_withholding_account=1) are always excluded."""
        expense_row = _dict(account="Expense-ACC", debit=1000.0, credit=0.0,
                            is_tax_withholding_account=0)
        tds_row = _dict(account="TDS-ACC", debit=0.0, credit=17.85,
                        is_tax_withholding_account=1)
        supplier_row = _dict(account="Supplier-AP", debit=0.0, credit=1190.0,
                             is_tax_withholding_account=0)

        from isnack.overrides.journal_entry import _GrossJournalEntryTaxWithholding

        handler = _GrossJournalEntryTaxWithholding.__new__(
            _GrossJournalEntryTaxWithholding
        )
        handler.doc = MagicMock()
        handler.doc.get = lambda key: [expense_row, tds_row, supplier_row]
        handler.doc.company = "Test Company"
        handler.party_account = "Supplier-AP"
        handler.party_field = "credit"
        handler.reverse_field = "debit"
        handler.precision = 2

        result = handler._calculate_net_total()
        # Gross should only include expense_row (1000); supplier excluded by party_account
        self.assertAlmostEqual(result, 1000.0, places=2)


class TestCustomJournalEntryApplyTaxWithholding(unittest.TestCase):
    """Tests that CustomJournalEntry dispatches to gross or net handler."""

    def _make_je(self, category="TDS-TN"):
        from isnack.overrides.journal_entry import CustomJournalEntry

        je = CustomJournalEntry.__new__(CustomJournalEntry)
        je.apply_tds = 1
        je.tax_withholding_category = category
        je.multi_currency = False
        je.cheque_no = None
        return je

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_gross_mode_uses_gross_handler(self, mock_get_value):
        """Gross Total mode: _GrossJournalEntryTaxWithholding.apply() is called."""
        mock_get_value.return_value = "Gross Total"
        je = self._make_je()

        with patch(
            "isnack.overrides.journal_entry._GrossJournalEntryTaxWithholding.apply"
        ) as mock_apply:
            je.apply_tax_withholding()
            mock_apply.assert_called_once()

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_net_mode_delegates_to_super(self, mock_get_value):
        """Net Total mode: super().apply_tax_withholding() is called."""
        mock_get_value.return_value = "Net Total"
        je = self._make_je()

        with patch(
            "isnack.overrides.journal_entry.JournalEntry.apply_tax_withholding"
        ) as mock_super:
            je.apply_tax_withholding()
            mock_super.assert_called_once()

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_no_category_delegates_to_super(self, mock_get_value):
        """When no category is set, super().apply_tax_withholding() is called."""
        mock_get_value.return_value = "Net Total"
        je = self._make_je()
        je.tax_withholding_category = None

        with patch(
            "isnack.overrides.journal_entry.JournalEntry.apply_tax_withholding"
        ) as mock_super:
            je.apply_tax_withholding()
            mock_super.assert_called_once()

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_apply_tds_false_delegates_to_super(self, mock_get_value):
        """When apply_tds=0, super().apply_tax_withholding() is called."""
        mock_get_value.return_value = "Gross Total"
        je = self._make_je()
        je.apply_tds = 0

        with patch(
            "isnack.overrides.journal_entry.JournalEntry.apply_tax_withholding"
        ) as mock_super:
            je.apply_tax_withholding()
            mock_super.assert_called_once()


# ---------------------------------------------------------------------------
# 5. compute_pe_gross_total helper
# ---------------------------------------------------------------------------


class TestComputePeGrossTotal(unittest.TestCase):
    """Tests for ``compute_pe_gross_total``."""

    def test_single_reference_full_payment(self):
        from isnack.overrides.tax_withholding import compute_pe_gross_total

        pe = _dict(
            references=[_dict(allocated_amount=1190.0, outstanding_amount=1190.0)],
            unallocated_amount=0.0,
        )
        result = compute_pe_gross_total(pe)
        self.assertAlmostEqual(result, 1190.0, places=2)

    def test_single_reference_partial_payment(self):
        from isnack.overrides.tax_withholding import compute_pe_gross_total

        pe = _dict(
            references=[_dict(allocated_amount=500.0, outstanding_amount=1190.0)],
            unallocated_amount=0.0,
        )
        result = compute_pe_gross_total(pe)
        self.assertAlmostEqual(result, 500.0, places=2)

    def test_with_unallocated_amount(self):
        from isnack.overrides.tax_withholding import compute_pe_gross_total

        pe = _dict(
            references=[_dict(allocated_amount=800.0, outstanding_amount=800.0)],
            unallocated_amount=200.0,
        )
        result = compute_pe_gross_total(pe)
        self.assertAlmostEqual(result, 1000.0, places=2)

    def test_no_references(self):
        from isnack.overrides.tax_withholding import compute_pe_gross_total

        pe = _dict(references=[], unallocated_amount=500.0)
        result = compute_pe_gross_total(pe)
        self.assertAlmostEqual(result, 500.0, places=2)


# ---------------------------------------------------------------------------
# 6. Backward-compatibility regression: monkey-patch preserves net behavior
# ---------------------------------------------------------------------------


class TestBackwardCompatibilityNetTotal(unittest.TestCase):
    """Regression tests: existing Net Total flows are fully unchanged."""

    NET = 1000.0

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_patched_function_calls_original_for_net_mode(self, mock_get_value):
        """When basis is Net Total, _original_get_tds_amount is called without any mutation."""
        from isnack.overrides.tax_withholding import _patched_get_tds_amount

        mock_get_value.return_value = "Net Total"

        inv = _dict(
            doctype="Purchase Invoice",
            tax_withholding_net_total=self.NET,
            base_tax_withholding_net_total=self.NET,
            grand_total=1190.0,
            base_grand_total=1190.0,
        )
        tax_details = _dict(
            tax_withholding_category="TDS-5%",
            rate=5.0,
            threshold=0,
            cumulative_threshold=0,
        )

        captured = {}

        def _fake_original(ldc, parties, inv, td, vwa):
            captured["tax_withholding_net_total"] = inv.get("tax_withholding_net_total")
            return inv.get("tax_withholding_net_total") * td.rate / 100

        with patch(
            "isnack.overrides.tax_withholding._original_get_tds_amount",
            side_effect=_fake_original,
        ):
            result = _patched_get_tds_amount(None, [], inv, tax_details, [])

        # Must have used the net value (1000), NOT the gross (1190)
        self.assertAlmostEqual(captured["tax_withholding_net_total"], self.NET, places=2)
        self.assertAlmostEqual(result, 50.0, places=2)

    @patch("isnack.overrides.tax_withholding.frappe.db.get_value")
    def test_patched_function_skips_mutation_for_no_category(self, mock_get_value):
        """When category is None / blank, original is called unchanged."""
        from isnack.overrides.tax_withholding import _patched_get_tds_amount

        mock_get_value.return_value = ""

        inv = _dict(
            doctype="Purchase Invoice",
            tax_withholding_net_total=self.NET,
            base_tax_withholding_net_total=self.NET,
        )
        tax_details = _dict(
            tax_withholding_category=None,
            rate=5.0,
            threshold=0,
            cumulative_threshold=0,
        )

        with patch(
            "isnack.overrides.tax_withholding._original_get_tds_amount",
            return_value=50.0,
        ) as mock_original:
            result = _patched_get_tds_amount(None, [], inv, tax_details, [])

        mock_original.assert_called_once()
        self.assertEqual(result, 50.0)
        self.assertEqual(inv.tax_withholding_net_total, self.NET)


# ---------------------------------------------------------------------------
# 7. get_gross_withholding_basis helper
# ---------------------------------------------------------------------------


class TestGetGrossWithholdingBasis(unittest.TestCase):
    """Tests for ``get_gross_withholding_basis``."""

    def test_purchase_invoice_uses_grand_total(self):
        from isnack.overrides.tax_withholding import get_gross_withholding_basis

        inv = _dict(
            doctype="Purchase Invoice",
            grand_total=1190.0,
            base_grand_total=1190.0,
            tax_withholding_net_total=1000.0,
        )
        gross, base_gross = get_gross_withholding_basis(inv)
        self.assertAlmostEqual(gross, 1190.0, places=2)
        self.assertAlmostEqual(base_gross, 1190.0, places=2)

    def test_payment_entry_uses_gross_total_attr(self):
        from isnack.overrides.tax_withholding import get_gross_withholding_basis

        inv = _dict(
            doctype="Payment Entry",
            _gross_total=1190.0,
            paid_amount=1172.15,
        )
        gross, base_gross = get_gross_withholding_basis(inv)
        self.assertAlmostEqual(gross, 1190.0, places=2)

    def test_payment_entry_falls_back_to_paid_amount(self):
        from isnack.overrides.tax_withholding import get_gross_withholding_basis

        inv = _dict(
            doctype="Payment Entry",
            paid_amount=1190.0,
        )
        gross, base_gross = get_gross_withholding_basis(inv)
        self.assertAlmostEqual(gross, 1190.0, places=2)

    def test_journal_entry_uses_gross_total_attr(self):
        from isnack.overrides.tax_withholding import get_gross_withholding_basis

        inv = _dict(
            doctype="Journal Entry",
            _gross_total=1190.0,
            tax_withholding_net_total=1000.0,
        )
        gross, _ = get_gross_withholding_basis(inv)
        self.assertAlmostEqual(gross, 1190.0, places=2)

    def test_unknown_doctype_falls_back_to_net(self):
        from isnack.overrides.tax_withholding import get_gross_withholding_basis

        inv = _dict(
            doctype="Unknown Doctype",
            tax_withholding_net_total=1000.0,
            base_tax_withholding_net_total=1000.0,
        )
        gross, base_gross = get_gross_withholding_basis(inv)
        self.assertAlmostEqual(gross, 1000.0, places=2)
        self.assertAlmostEqual(base_gross, 1000.0, places=2)


if __name__ == "__main__":
    unittest.main()
