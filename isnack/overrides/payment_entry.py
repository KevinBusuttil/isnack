# Copyright (c) 2025, Busuttil Technologies Limited
# License: MIT
"""
Custom Payment Entry class that adds Gross Total withholding basis support.

When ``custom_deduct_tax_on_basis`` is set to ``"Gross Total"`` on the active
Tax Withholding Category, ``calculate_tax_withholding_net_total`` returns the
gross (TTC) amount instead of the net amount.
"""

from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry

from isnack.overrides.tax_withholding import compute_pe_gross_total, is_gross_basis_enabled


class CustomPaymentEntry(PaymentEntry):
    """Payment Entry with configurable withholding basis (Net or Gross Total)."""

    def calculate_tax_withholding_net_total(self):
        """Return the withholding basis amount.

        Net Total mode (default)
            Delegates to the parent implementation – preserves existing ERPNext 15
            behavior that derives the net amount from referenced order/invoice data.

        Gross Total mode
            Returns the sum of allocated amounts across all references plus any
            unallocated amount, representing the full TTC payment basis.
        """
        if is_gross_basis_enabled(self.tax_withholding_category):
            return compute_pe_gross_total(self)

        return super().calculate_tax_withholding_net_total()
