"""
conftest.py – inject stub modules so that isnack tests can run without a
live Frappe/ERPNext installation.

pytest loads conftest.py files before collecting or importing any test
modules, which means these stubs are in sys.modules before isnack/__init__.py
is imported.
"""
import sys
from unittest.mock import MagicMock


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


# Only install stubs when the real modules are not available (i.e. outside a
# Frappe bench environment).
if "erpnext" not in sys.modules:
    _twc_stub = MagicMock()
    _twc_stub.get_tds_amount = MagicMock(return_value=0.0)

    _frappe_stub = MagicMock()
    _frappe_stub._dict = _FrappeDict
    _frappe_stub.db = MagicMock()

    _je_stub = MagicMock()
    # Make JournalEntryTaxWithholding importable as a real (new-style) class
    class _JETaxWithholding:
        def __init__(self, je):
            self.doc = je
            self.party = None
            self.party_type = None
            self.party_account = None
            self.party_row = None
            self.existing_tds_rows = []
            self.precision = 2
            self.has_multiple_parties = False
            self.party_field = None
            self.reverse_field = None

        def apply(self):
            pass

        def _set_party_info(self):
            return True

        def _setup_direction_fields(self):
            pass

        def _calculate_net_total(self):
            return 0.0

    class _JournalEntry:
        """Stub base class for CustomJournalEntry."""

        def get(self, key=None, default=None):
            return getattr(self, key, default)

        def validate(self):
            pass

        def apply_tax_withholding(self):
            pass

        def set_amounts_in_company_currency(self):
            pass

    _je_stub.JournalEntry = _JournalEntry
    _je_stub.JournalEntryTaxWithholding = _JETaxWithholding
    _je_stub.get_exchange_rate = MagicMock()

    _pe_stub = MagicMock()

    class _PaymentEntry:
        """Stub base class for CustomPaymentEntry."""

        def calculate_tax_withholding_net_total(self):
            return 0.0

        def set_tax_withholding(self):
            pass

        def get(self, key, default=None):
            return getattr(self, key, default)

    _pe_stub.PaymentEntry = _PaymentEntry

    stubs = {
        "frappe": _frappe_stub,
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
        "erpnext.accounts.doctype.payment_entry.payment_entry": _pe_stub,
        "erpnext.accounts.doctype.journal_entry": MagicMock(),
        "erpnext.accounts.doctype.journal_entry.journal_entry": _je_stub,
        "erpnext.controllers": MagicMock(),
        "erpnext.controllers.accounts_controller": MagicMock(),
    }

    for mod_name, stub in stubs.items():
        sys.modules[mod_name] = stub
