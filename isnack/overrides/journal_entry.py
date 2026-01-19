# Copyright (c) 2024, Busuttil Technologies Limited
# License: MIT
# This file implements the fix from ERPNext PR #43331 for multi-currency Journal Entries
# https://github.com/frappe/erpnext/pull/43331

import frappe
from frappe.utils import flt

from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry


class CustomJournalEntry(JournalEntry):
    """
    Custom Journal Entry class that fixes transaction exchange rate handling
    for multi-currency Journal Entries.
    
    Issue: In standard ERPNext v15, GL entries for all rows in multi-currency 
    Journal Entries incorrectly use the same exchange rate from the first row.
    
    Fix: Use the row-specific exchange rate for each Journal Entry line item.
    """

    def get_gl_dict(self, args, account_currency=None, item=None):
        """
        Override get_gl_dict to fix transaction exchange rate on GL entries 
        for multi-currency Journal Entries.
        
        This implements the fix from ERPNext PR #43331:
        https://github.com/frappe/erpnext/pull/43331
        """
        # Call the parent method to get the standard GL dict
        gl_dict = super().get_gl_dict(args, account_currency, item)
        
        # Apply the fix: use row-specific exchange rate for Journal Entries
        # instead of the document-level conversion_rate
        if item and item.get("exchange_rate"):
            gl_dict["transaction_exchange_rate"] = flt(item.get("exchange_rate", 1))
        
        return gl_dict
