# Copyright (c) 2026, Busuttil Technologies Limited
# License: MIT
# Custom Payment Reconciliation override
# Adds:
#   1. suppress_exchange_gain_loss: zeroes out difference_amount on all allocation rows
#      when the user opts to reconcile without exchange gain/loss posting.
#   2. custom_reconciliation_date: auto-populated on every allocation row for audit trail.

import frappe
from frappe.utils import nowdate

from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import PaymentReconciliation


class CustomPaymentReconciliation(PaymentReconciliation):
    """
    Custom Payment Reconciliation class.

    Extends standard ERPNext PaymentReconciliation with:
    - suppress_exchange_gain_loss: When checked, zeroes out the difference_amount on
      all allocation rows so no Exchange Gain/Loss journal entry is created on reconcile.
    - custom_reconciliation_date: Automatically populated on every allocation row with
      today's date when entries are allocated, providing a full audit trail date on all
      reconciliations (not just those with an exchange difference).
    """

    @frappe.whitelist()
    def allocate_entries(self, args: dict):
        # Run standard ERPNext allocation logic first
        super().allocate_entries(args)

        suppress = self.get("suppress_exchange_gain_loss")

        for row in self.get("allocation"):
            # Feature 2: set reconciliation date on every allocation row
            if not row.get("custom_reconciliation_date"):
                row.custom_reconciliation_date = nowdate()

            # Feature 1: suppress exchange gain/loss if requested
            if suppress:
                row.difference_amount = 0
                row.difference_account = None
