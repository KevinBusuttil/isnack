# Copyright (c) 2025, Busuttil Technologies Limited
# License: MIT
"""
Override for ERPNext 15 withholding computation to support ``custom_deduct_tax_on_basis``.

ERPNext 15 supplier-side withholding is NET-based by default. This module adds support
for a configurable "Gross Total" (TTC including VAT) basis, required for Tunisia
domestic B2B supplier withholding.

The ``custom_deduct_tax_on_basis`` field on Tax Withholding Category controls the basis:
  - ``Net Total``  (default): preserves existing ERPNext 15 behavior
  - ``Gross Total``: withholding is computed on the gross/TTC amount including VAT

Design notes:
  - Threshold eligibility and actual withholding deduction are kept as separate concepts.
  - The ``custom_deduct_tax_on_basis`` field controls the basis for actual withholding
    deduction AND threshold checking, so both are consistently gross for Tunisia.
  - All non-gross-mode paths are unchanged (backward compatible).

Document type coverage:
  - Purchase Invoice: monkey-patched via ``_patched_get_tds_amount`` in this module.
  - Payment Entry: handled in ``CustomPaymentEntry.calculate_tax_withholding_net_total``.
  - Journal Entry: handled in ``CustomJournalEntry.apply_tax_withholding``.
"""

import frappe
from frappe.utils import flt

import erpnext.accounts.doctype.tax_withholding_category.tax_withholding_category as _twc_mod

# Keep a reference to the original so we can call through to it.
_original_get_tds_amount = _twc_mod.get_tds_amount


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_deduct_tax_on_basis(tax_withholding_category):
    """Return the configured deduction basis for *tax_withholding_category*.

    Returns ``"Net Total"`` (the default) when:
    - the argument is blank / ``None``
    - the custom field is not yet installed
    - the stored value is blank
    """
    if not tax_withholding_category:
        return "Net Total"
    try:
        value = frappe.db.get_value(
            "Tax Withholding Category",
            tax_withholding_category,
            "custom_deduct_tax_on_basis",
        )
        return value or "Net Total"
    except Exception:
        return "Net Total"


def is_gross_basis_enabled(tax_withholding_category):
    """Return ``True`` when gross-total withholding is configured for *tax_withholding_category*."""
    return get_deduct_tax_on_basis(tax_withholding_category) == "Gross Total"


def get_net_withholding_basis(inv):
    """Return the net withholding basis amounts ``(net, base_net)`` – existing ERPNext behavior."""
    return (
        flt(inv.get("tax_withholding_net_total", 0)),
        flt(inv.get("base_tax_withholding_net_total", 0)),
    )


def get_gross_withholding_basis(inv):
    """Return ``(gross, base_gross)`` withholding amounts (TTC including VAT).

    For Purchase Invoice
        ``inv.grand_total`` / ``inv.base_grand_total`` are the pre-TDS gross totals
        (available because ``set_tax_withholding`` is called before the TDS row is
        added to the taxes table for the first time).

    For Payment Entry
        A ``_gross_total`` attribute is injected by ``CustomPaymentEntry``
        before ``get_party_tax_withholding_details`` is called.  Falls back to
        ``paid_amount`` when not set.

    For Journal Entry
        A ``_gross_total`` attribute is injected by ``CustomJournalEntry``
        (computed by ``compute_je_gross_total``).  Falls back to the stored
        ``tax_withholding_net_total`` when not set.
    """
    doctype = inv.get("doctype", "")

    if doctype == "Purchase Invoice":
        # grand_total at this point is the pre-TDS gross (TTC including VAT).
        gross = flt(inv.get("grand_total", 0))
        base_gross = flt(inv.get("base_grand_total", 0))
        return gross, base_gross

    if doctype == "Payment Entry":
        # CustomPaymentEntry injects _gross_total before this is reached.
        gross = flt(inv.get("_gross_total") or inv.get("paid_amount", 0))
        return gross, gross

    if doctype == "Journal Entry":
        # CustomJournalEntry injects _gross_total before this is reached.
        gross = flt(inv.get("_gross_total", 0))
        if not gross:
            gross = flt(inv.get("tax_withholding_net_total", 0))
        return gross, gross

    # Generic fallback – return the net basis unchanged.
    return get_net_withholding_basis(inv)


def compute_pe_gross_total(pe_doc):
    """Compute the gross withholding basis for a Payment Entry.

    The gross basis for a PE is the sum of the gross (allocated) amounts from
    each invoice reference plus any unallocated amount.  This represents the
    full TTC amount being settled by the payment.
    """
    gross_total = 0.0
    for ref in getattr(pe_doc, "references", None) or []:
        allocated = flt(ref.get("allocated_amount", 0) if hasattr(ref, "get") else getattr(ref, "allocated_amount", 0))
        outstanding = flt(ref.get("outstanding_amount", 0) if hasattr(ref, "get") else getattr(ref, "outstanding_amount", 0))
        gross_total += min(allocated, outstanding) if outstanding else allocated
    gross_total += flt(getattr(pe_doc, "unallocated_amount", 0))
    return gross_total


def compute_je_gross_total(je_handler):
    """Compute the gross withholding basis for a Journal Entry.

    The gross total includes Tax and Chargeable account rows, unlike the
    standard :pymeth:`_calculate_net_total` which excludes them.
    """
    return flt(
        sum(
            d.get(je_handler.reverse_field, 0) - d.get(je_handler.party_field, 0)
            for d in je_handler.doc.get("accounts")
            if d.account != je_handler.party_account
            and not d.get("is_tax_withholding_account")
        ),
        je_handler.precision,
    )


# ---------------------------------------------------------------------------
# Monkey-patch for Purchase Invoice
# ---------------------------------------------------------------------------


def _patched_get_tds_amount(ldc, parties, inv, tax_details, voucher_wise_amount):
    """Patched ``get_tds_amount`` that supports ``custom_deduct_tax_on_basis``.

    When the category is configured for ``Gross Total``:
    - ``inv.tax_withholding_net_total`` is temporarily replaced with the gross value.
    - ``inv.base_tax_withholding_net_total`` is temporarily replaced with the base gross.
    - The original function is called with these gross values as the effective basis.
    - The original values are restored after the call.

    For document types other than Purchase Invoice, gross amounts come from a
    ``_gross_total`` attribute injected by the respective custom doctype classes.
    """
    category = tax_details.get("tax_withholding_category")

    if not is_gross_basis_enabled(category):
        return _original_get_tds_amount(ldc, parties, inv, tax_details, voucher_wise_amount)

    # Save originals
    original_net = inv.get("tax_withholding_net_total")
    original_base_net = inv.get("base_tax_withholding_net_total")

    # Replace with gross values
    gross, base_gross = get_gross_withholding_basis(inv)
    inv["tax_withholding_net_total"] = gross
    inv["base_tax_withholding_net_total"] = base_gross

    try:
        result = _original_get_tds_amount(ldc, parties, inv, tax_details, voucher_wise_amount)
    finally:
        # Always restore – even if an exception occurs
        inv["tax_withholding_net_total"] = original_net
        inv["base_tax_withholding_net_total"] = original_base_net

    return result


# ---------------------------------------------------------------------------
# Apply the monkey-patch
# ---------------------------------------------------------------------------


def apply():
    """Replace ``get_tds_amount`` in the ERPNext module with the patched version.

    Called from ``isnack/__init__.py`` at application import time.
    """
    _twc_mod.get_tds_amount = _patched_get_tds_amount
