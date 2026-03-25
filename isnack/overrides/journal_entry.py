# Copyright (c) 2024, Busuttil Technologies Limited
# License: MIT
# This file implements the fix from ERPNext PR #43331 for multi-currency Journal Entries
# https://github.com/frappe/erpnext/pull/43331
# Also adds Gross Total withholding basis support for Journal Entry.

import erpnext
import frappe
from frappe.utils import flt

from erpnext.accounts.doctype.journal_entry.journal_entry import (
    JournalEntry,
    get_exchange_rate,
)
from erpnext.accounts.doctype.tax_withholding_entry.tax_withholding_entry import (
    JournalTaxWithholding,
)


class _GrossJournalEntryTaxWithholding(JournalTaxWithholding):
    """Journal Entry withholding handler that computes the basis on gross (TTC) amounts.

    Overrides ``_calculate_net_total`` to include Tax and Chargeable account rows
    that the standard implementation deliberately excludes.
    """

    def _calculate_net_total(self):
        from isnack.overrides.tax_withholding import compute_je_gross_total

        return compute_je_gross_total(self)


class CustomJournalEntry(JournalEntry):
    """
    Custom Journal Entry class that:

    1. Fixes transaction exchange rate handling for multi-currency Journal Entries
       (ERPNext PR #43331 backport).

    2. Supports ``custom_deduct_tax_on_basis = "Gross Total"`` on Tax Withholding
       Category for gross/TTC supplier withholding (e.g. Tunisia domestic B2B).
    """

    def apply_tax_withholding(self):
        """Dispatch to gross or net withholding handler based on category configuration."""
        from isnack.overrides.tax_withholding import is_gross_basis_enabled

        if (
            self.apply_tds
            and self.tax_withholding_category
            and is_gross_basis_enabled(self.tax_withholding_category)
        ):
            _GrossJournalEntryTaxWithholding(self).apply()
        else:
            super().apply_tax_withholding()

    def _is_from_service_invoice(self):
        """
        Check if this Journal Entry originated from a Service Invoice.
        
        The Service Invoice module creates Journal Entries using JournalEntryBuilder, which 
        sets the `cheque_no` field to the Service Invoice's name for tracking purposes.
        This is the standard way Service Invoice JEs are identified in the system.
        See: JournalEntryBuilder.set_header() in isnack/isnack/doctype/service_invoice/service_invoice.py
        
        Returns:
            bool: True if the JE originated from a Service Invoice, False otherwise.
        """
        return self.cheque_no and frappe.db.exists("Service Invoice", self.cheque_no)
    
    def validate(self):
        # Only fix exchange rates for multi-currency JEs from Service Invoices
        # Manual JEs should use standard ERPNext behavior where account currency amounts
        # are the source of truth
        if self.multi_currency and self._is_from_service_invoice():
            self.fix_multi_currency_exchange_rates()

        # Now call parent validate
        super().validate()
    
    def set_amounts_in_company_currency(self):
        """
        Override to prevent ERPNext from overwriting company currency amounts
        when they are already set (i.e., when company amounts are the source of truth).
        
        Standard ERPNext behavior: debit = debit_in_account_currency × exchange_rate
        Custom behavior (for multi-currency JEs from Service Invoices): If debit/credit 
        is already set, keep it and recalculate account currency amounts instead.
        """
        # Only apply custom logic for multi-currency JEs from Service Invoices
        use_custom_logic = self.multi_currency and self._is_from_service_invoice()
        
        if not (self.voucher_type == "Exchange Gain Or Loss" and self.multi_currency):
            for d in self.get("accounts"):
                d.debit_in_account_currency = flt(
                    d.debit_in_account_currency, d.precision("debit_in_account_currency")
                )
                d.credit_in_account_currency = flt(
                    d.credit_in_account_currency, d.precision("credit_in_account_currency")
                )
                
                # Apply custom logic only for multi-currency JEs from Service Invoices
                if use_custom_logic and (flt(d.debit) or flt(d.credit)):
                    # Custom behavior: Company currency amounts are source of truth
                    # Recalculate account currency amounts
                    exchange_rate = flt(d.exchange_rate) or 1.0
                    
                    if flt(d.debit):
                        d.debit = flt(d.debit, d.precision("debit"))
                        d.debit_in_account_currency = flt(
                            d.debit / exchange_rate,
                            d.precision("debit_in_account_currency")
                        )
                    
                    if flt(d.credit):
                        d.credit = flt(d.credit, d.precision("credit"))
                        d.credit_in_account_currency = flt(
                            d.credit / exchange_rate,
                            d.precision("credit_in_account_currency")
                        )
                else:
                    # Standard ERPNext behavior: calculate company amounts from account currency amounts
                    d.debit = flt(
                        d.debit_in_account_currency * flt(d.exchange_rate),
                        d.precision("debit")
                    )
                    d.credit = flt(
                        d.credit_in_account_currency * flt(d.exchange_rate),
                        d.precision("credit")
                    )

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
            account = frappe.get_cached_value("Account", d.account, ["account_currency", "account_type"], as_dict=1)
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
                        d.debit_in_account_currency = flt(flt(d.debit) / correct_exchange_rate, d.precision("debit_in_account_currency"))

                    if flt(d.credit):
                        d.credit_in_account_currency = flt(flt(d.credit) / correct_exchange_rate, d.precision("credit_in_account_currency"))
                    
                    d.exchange_rate = correct_exchange_rate
                
                elif flt(d.debit_in_account_currency) or flt(d.credit_in_account_currency):
                    # If only account currency amounts are set, just update the exchange rate
                    # The parent's set_amounts_in_company_currency will calculate company amounts
                    d.exchange_rate = correct_exchange_rate

