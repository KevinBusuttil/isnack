# Copyright (c) 2024, Busuttil Technologies Limited
# License: MIT
# This file implements the fix from ERPNext PR #43331 for multi-currency Journal Entries
# https://github.com/frappe/erpnext/pull/43331

import erpnext
import frappe
from frappe.utils import flt

from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry, get_exchange_rate


class CustomJournalEntry(JournalEntry):
    """
    Custom Journal Entry class that fixes transaction exchange rate handling
    for multi-currency Journal Entries.
    
    Issue: In standard ERPNext v15, GL entries for all rows in multi-currency 
    Journal Entries incorrectly use the same exchange rate from the first row.
    
    Fix: Use the row-specific exchange rate for each Journal Entry line item.
    """

    def validate(self):
        # First, fix exchange rates and recalculate account currency amounts
        # BEFORE the parent validate runs set_amounts_in_company_currency
        if self.multi_currency:
            self.fix_multi_currency_exchange_rates()
        
        # Now call parent validate
        super().validate()

    def fix_multi_currency_exchange_rates(self):
        """
        For multi-currency Journal Entries, ensure each row has the correct
        exchange rate for its account currency, and recalculate the 
        debit_in_account_currency/credit_in_account_currency accordingly.
        
        The Company Currency amounts (debit/credit) are treated as the source
        of truth since that's what ultimately matters for the GL entries.
        """
        company_currency = erpnext.get_company_currency(self.company)
        
        for d in self.get("accounts"):
            if not d.account:
                continue
                
            # Get account details
            account = frappe.get_cached_value(
                "Account", d.account, ["account_currency", "account_type"], as_dict=1
            )
            if not account:
                continue
            
            d.account_currency = account.account_currency
            d.account_type = account.account_type
            
            # If account currency is same as company currency, exchange rate is 1
            if d.account_currency == company_currency:
                d.exchange_rate = 1
                # Account currency amounts equal company currency amounts
                if flt(d.debit):
                    d.debit_in_account_currency = flt(d.debit, d.precision("debit_in_account_currency"))
                if flt(d.credit):
                    d.credit_in_account_currency = flt(d.credit, d.precision("credit_in_account_currency"))
            else:
                # Get the correct exchange rate for this account's currency
                correct_exchange_rate = get_exchange_rate(
                    self.posting_date,
                    d.account,
                    d.account_currency,
                    self.company,
                    d.reference_type,
                    d.reference_name,
                    d.debit,
                    d.credit,
                    None,  # Don't pass existing exchange rate - we want fresh rate
                )
                
                if not correct_exchange_rate or correct_exchange_rate <= 0:
                    frappe.log_error(
                        f"Exchange rate lookup failed for account {d.account} ({d.account_currency}). Using fallback rate of 1.",
                        "Journal Entry Exchange Rate Warning"
                    )
                    correct_exchange_rate = 1
                
                # If we have company currency amounts set, use them to recalculate
                # account currency amounts with the correct exchange rate
                if flt(d.debit) or flt(d.credit):
                    # Company currency amounts are the source of truth
                    # Recalculate account currency amounts using correct exchange rate
                    if flt(d.debit):
                        d.debit_in_account_currency = flt(
                            flt(d.debit) / correct_exchange_rate, 
                            d.precision("debit_in_account_currency")
                        )
                    if flt(d.credit):
                        d.credit_in_account_currency = flt(
                            flt(d.credit) / correct_exchange_rate,
                            d.precision("credit_in_account_currency")
                        )
                    
                    d.exchange_rate = correct_exchange_rate
                
                elif flt(d.debit_in_account_currency) or flt(d.credit_in_account_currency):
                    # If only account currency amounts are set, just update the exchange rate
                    # The parent's set_amounts_in_company_currency will calculate company amounts
                    d.exchange_rate = correct_exchange_rate

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
        if item:
            exchange_rate = item.get("exchange_rate")
            if exchange_rate:
                gl_dict["transaction_exchange_rate"] = flt(exchange_rate)
        
        return gl_dict
