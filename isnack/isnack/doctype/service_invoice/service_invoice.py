# Copyright (c) 2023, Busuttil Technologies Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, round_based_on_smallest_currency_fraction
from erpnext import get_default_company, get_company_currency
from erpnext.setup.utils import get_exchange_rate


class AmountCalculator:
    """Handles VAT-inclusive vs VAT-exclusive amount calculations with proper rounding."""
    
    def __init__(self, gross_amount, tax_rate, account_currency, vat_inclusive=False):
        """
        Initialize amount calculator.
        
        Args:
            gross_amount: The total amount from the invoice line
            tax_rate: Tax rate as a percentage (e.g., 19.0 for 19%)
            account_currency: Currency for rounding calculations
            vat_inclusive: Whether VAT is included in gross_amount
        """
        self.gross_amount = flt(gross_amount)
        self.tax_rate = flt(tax_rate)
        self.account_currency = account_currency
        self.vat_inclusive = vat_inclusive
        self.account_precision = frappe.get_precision(
            "Journal Entry Account",
            "debit_in_account_currency",
            currency=account_currency,
        ) or 2
    
    def calculate(self):
        """
        Calculate invoice amount (party line) and VAT amount.
        
        Returns:
            dict: {
                'invoice_amount': Amount for party line (account currency),
                'vat_amount': VAT amount (account currency)
            }
        """
        if self.vat_inclusive:
            # VAT is included in gross: extract the base amount
            divisor = (self.tax_rate + 100.0) / 100.0 if self.tax_rate else 1.0
            invoice_amount = self.gross_amount / divisor
            vat_amount = self.gross_amount - invoice_amount
        else:
            # VAT is exclusive: calculate VAT on top
            vat_amount = self.gross_amount * (self.tax_rate / 100.0) if self.tax_rate else 0.0
            invoice_amount = self.gross_amount + vat_amount
        
        # Round both amounts in account currency
        invoice_amount = round_based_on_smallest_currency_fraction(
            invoice_amount, self.account_currency, self.account_precision
        )
        vat_amount = round_based_on_smallest_currency_fraction(
            vat_amount, self.account_currency, self.account_precision
        )
        
        return {
            'invoice_amount': invoice_amount,
            'vat_amount': vat_amount
        }


class JournalEntryBuilder:
    """Handles multi-currency journal entry creation with proper rounding and balancing."""
    
    def __init__(self, inv, company, company_currency):
        """
        Initialize the journal entry builder.
        
        Args:
            inv: Service invoice item row
            company: Company name
            company_currency: Company's base currency
        """
        self.inv = inv
        self.company = company
        self.company_currency = company_currency
        self.company_precision = frappe.get_precision(
            "Journal Entry Account",
            "debit",
            currency=company_currency,
        ) or 2
        
        # Get exchange rates
        self.account_exchange_rate = flt(get_exchange_rate(
            inv.account_currency, company_currency, inv.date
        )) or 1.0
        self.offset_exchange_rate = flt(get_exchange_rate(
            inv.offset_account_currency, company_currency, inv.date
        )) or 1.0
        
        # Initialize journal entry
        self.jv = frappe.new_doc("Journal Entry")
        self.jv.voucher_type = "Journal Entry"
        self.jv.company = company
        
        # Track rows for balancing
        self.party_row = None
        self.offset_row = None
        self.vat_row = None
    
    def set_header(self, naming_series, posting_date, user_remark, cheque_no, cheque_date,
                   multi_currency=False, bill_no=None, bill_date=None, due_date=None):
        """Set journal entry header fields."""
        self.jv.naming_series = naming_series
        self.jv.posting_date = posting_date
        self.jv.multi_currency = multi_currency
        self.jv.user_remark = user_remark
        self.jv.cheque_no = cheque_no
        self.jv.cheque_date = cheque_date
        
        if bill_no:
            self.jv.bill_no = bill_no
        if bill_date:
            self.jv.bill_date = bill_date
        if due_date:
            self.jv.due_date = due_date
    
    def convert_to_company_currency(self, amount, from_currency, exchange_rate=None):
        """
        Convert amount to company currency with proper rounding.
        
        Args:
            amount: Amount in source currency
            from_currency: Source currency code
            exchange_rate: Optional exchange rate (auto-fetched if not provided)
        
        Returns:
            float: Amount in company currency, properly rounded
        """
        if exchange_rate is None:
            exchange_rate = flt(get_exchange_rate(
                from_currency, self.company_currency, self.inv.date
            )) or 1.0
        
        company_amount = flt(amount) * flt(exchange_rate)
        return round_based_on_smallest_currency_fraction(
            company_amount, self.company_currency, self.company_precision
        )
    
    def convert_between_currencies(self, amount, from_currency, to_currency,
                                   from_rate=None, to_rate=None):
        """
        Convert amount between two currencies via company currency.
        
        Args:
            amount: Amount in source currency
            from_currency: Source currency code
            to_currency: Target currency code
            from_rate: Exchange rate from source to company currency
            to_rate: Exchange rate from target to company currency
        
        Returns:
            tuple: (amount_in_target_currency, amount_in_company_currency)
        """
        # Convert to company currency first
        company_amount = self.convert_to_company_currency(amount, from_currency, from_rate)
        
        # Convert from company currency to target currency
        if to_rate is None:
            to_rate = flt(get_exchange_rate(
                to_currency, self.company_currency, self.inv.date
            )) or 1.0
        
        target_amount = company_amount / flt(to_rate)
        
        # Round in target currency
        target_precision = frappe.get_precision(
            "Journal Entry Account",
            "debit_in_account_currency",
            currency=to_currency,
        ) or 2
        target_amount = round_based_on_smallest_currency_fraction(
            target_amount, to_currency, target_precision
        )
        
        return target_amount, company_amount
    
    def add_line(self, account, account_currency, debit_acc=None, credit_acc=None,
                party_type=None, party=None, cost_center=None, exchange_rate=None):
        """
        Add a journal entry line with proper multi-currency handling.
        
        Args:
            account: Account name
            account_currency: Currency of the account
            debit_acc: Debit amount in account currency
            credit_acc: Credit amount in account currency
            party_type: Optional party type
            party: Optional party name
            cost_center: Optional cost center
            exchange_rate: Optional exchange rate (auto-fetched if not provided)
        
        Returns:
            dict: The created row
        """
        row = {"account": account}
        
        if cost_center:
            row["cost_center"] = cost_center
        if party_type and party:
            row["party_type"] = party_type
            row["party"] = party
        
        # Set account currency amounts
        if debit_acc is not None:
            row["debit_in_account_currency"] = flt(debit_acc)
            # Convert to company currency
            row["debit"] = self.convert_to_company_currency(
                debit_acc, account_currency, exchange_rate
            )
        
        if credit_acc is not None:
            row["credit_in_account_currency"] = flt(credit_acc)
            # Convert to company currency
            row["credit"] = self.convert_to_company_currency(
                credit_acc, account_currency, exchange_rate
            )
        
        self.jv.append("accounts", row)
        return row
    
    def add_party_line(self, invoice_amount, is_credit):
        """Add the party (supplier/customer) line."""
        if is_credit:
            self.party_row = self.add_line(
                account=self.inv.account,
                account_currency=self.inv.account_currency,
                credit_acc=invoice_amount,
                party_type=getattr(self.inv, "party_type", None),
                party=getattr(self.inv, "party", None),
                cost_center=self.inv.cost_center,
                exchange_rate=self.account_exchange_rate,
            )
        else:
            self.party_row = self.add_line(
                account=self.inv.account,
                account_currency=self.inv.account_currency,
                debit_acc=invoice_amount,
                party_type=getattr(self.inv, "party_type", None),
                party=getattr(self.inv, "party", None),
                cost_center=self.inv.cost_center,
                exchange_rate=self.account_exchange_rate,
            )
    
    def add_offset_line(self, offset_amount, is_credit, vat_inclusive=False, gross_amount=None):
        """
        Add the offset account line.
        
        Args:
            offset_amount: Amount for offset (in account currency if same, needs conversion if different)
            is_credit: Whether party line is credit (offset will be opposite)
            vat_inclusive: Whether VAT is inclusive
            gross_amount: Gross amount from invoice (used for VAT exclusive case)
        """
        # Determine the base amount for offset conversion
        if self.inv.account_currency != self.inv.offset_account_currency:
            # Multi-currency: convert from account currency to offset currency
            if vat_inclusive:
                base_amount = offset_amount  # Use invoice_amount
            else:
                base_amount = gross_amount if gross_amount is not None else offset_amount
            
            offset_acc_amount, offset_company_amount = self.convert_between_currencies(
                base_amount,
                self.inv.account_currency,
                self.inv.offset_account_currency,
                self.account_exchange_rate,
                self.offset_exchange_rate,
            )
        else:
            # Same currency: use the amount directly
            if vat_inclusive:
                offset_acc_amount = offset_amount
            else:
                offset_acc_amount = gross_amount if gross_amount is not None else offset_amount
            
            offset_company_amount = self.convert_to_company_currency(
                offset_acc_amount,
                self.inv.offset_account_currency,
                self.offset_exchange_rate,
            )
        
        # Create the offset line (opposite of party line)
        if is_credit:
            self.offset_row = self.add_line(
                account=self.inv.offset_account,
                account_currency=self.inv.offset_account_currency,
                debit_acc=offset_acc_amount,
                cost_center=self.inv.cost_center,
                exchange_rate=self.offset_exchange_rate,
            )
        else:
            self.offset_row = self.add_line(
                account=self.inv.offset_account,
                account_currency=self.inv.offset_account_currency,
                credit_acc=offset_acc_amount,
                cost_center=self.inv.cost_center,
                exchange_rate=self.offset_exchange_rate,
            )
    
    def add_vat_line(self, vat_amount, tax_account, is_credit):
        """Add the VAT line (typically in company currency)."""
        # Convert VAT to company currency
        vat_company_amount = self.convert_to_company_currency(
            vat_amount,
            self.inv.account_currency,
            self.account_exchange_rate,
        )
        
        # VAT line is opposite of party line
        if is_credit:
            self.vat_row = self.add_line(
                account=tax_account,
                account_currency=self.company_currency,
                debit_acc=vat_company_amount,
                cost_center=self.inv.cost_center,
                exchange_rate=1.0,  # Already in company currency
            )
        else:
            self.vat_row = self.add_line(
                account=tax_account,
                account_currency=self.company_currency,
                credit_acc=vat_company_amount,
                cost_center=self.inv.cost_center,
                exchange_rate=1.0,  # Already in company currency
            )
    
    def balance_journal_entry(self):
        """
        Balance the journal entry by adjusting for rounding differences.
        
        Adjusts the most appropriate line (prefer VAT > offset > party)
        to ensure total debit equals total credit in company currency.
        
        Zero out ultra-small differences below the smallest currency fraction
        and recompute account currency fields from rounded company amounts to
        avoid double-rounding drift.
        """
        total_debit = sum(flt(row.get("debit")) for row in self.jv.accounts)
        total_credit = sum(flt(row.get("credit")) for row in self.jv.accounts)
        diff = total_debit - total_credit
        
        # Round the difference to avoid tiny floating point errors
        diff = round_based_on_smallest_currency_fraction(
            diff, self.company_currency, self.company_precision
        )
        
        # Zero out ultra-small diffs below the smallest currency fraction
        # The smallest fraction is typically 0.01 for most currencies (1/100)
        # We use a more conservative threshold of half the smallest unit to account for rounding
        smallest_fraction = 1.0 / (10 ** self.company_precision)
        rounding_tolerance = smallest_fraction / 2
        
        # If the absolute difference is below the rounding tolerance, zero it out
        # This prevents tiny floating-point errors from causing validation failures
        if abs(diff) < rounding_tolerance:
            diff = 0.0
        
        if not diff:
            return  # Already balanced
        
        # Choose which row to adjust (prefer VAT > offset > party)
        adjust_row = self.vat_row or self.offset_row or self.party_row
        if not adjust_row:
            return  # No rows to adjust
        
        # Determine the currency of the adjustment row
        adjust_currency = None
        adjust_rate = 1.0
        
        if adjust_row is self.party_row:
            adjust_currency = self.inv.account_currency
            adjust_rate = self.account_exchange_rate
        elif adjust_row is self.offset_row:
            adjust_currency = self.inv.offset_account_currency
            adjust_rate = self.offset_exchange_rate
        elif adjust_row is self.vat_row:
            adjust_currency = self.company_currency
            adjust_rate = 1.0
        
        # Apply adjustment in company currency
        if diff > 0:
            # Too much debit, need more credit (or less debit)
            if adjust_row.get("credit"):
                adjust_row["credit"] = flt(adjust_row.get("credit")) + diff
            else:
                adjust_row["debit"] = flt(adjust_row.get("debit")) - diff
        else:
            # Too much credit, need more debit (or less credit)
            abs_diff = abs(diff)
            if adjust_row.get("debit"):
                adjust_row["debit"] = flt(adjust_row.get("debit")) + abs_diff
            else:
                adjust_row["credit"] = flt(adjust_row.get("credit")) - abs_diff
        
        # Round company currency amounts
        if adjust_row.get("debit"):
            adjust_row["debit"] = round_based_on_smallest_currency_fraction(
                adjust_row["debit"], self.company_currency, self.company_precision
            )
        if adjust_row.get("credit"):
            adjust_row["credit"] = round_based_on_smallest_currency_fraction(
                adjust_row["credit"], self.company_currency, self.company_precision
            )
        
        # Recompute account currency fields from rounded company amounts
        # to avoid double-rounding drift when the adjusted line currency differs from company currency
        if adjust_currency == self.company_currency:
            # If account currency is same as company currency, sync the fields
            if adjust_row.get("debit") is not None:
                adjust_row["debit_in_account_currency"] = adjust_row["debit"]
            if adjust_row.get("credit") is not None:
                adjust_row["credit_in_account_currency"] = adjust_row["credit"]
        else:
            # Recalculate account currency amounts from rounded company currency amounts
            # This ensures consistency and avoids double-rounding drift
            # Both debit_in_account_currency and credit_in_account_currency use the same precision
            account_precision = frappe.get_precision(
                "Journal Entry Account",
                "debit_in_account_currency",
                currency=adjust_currency,
            ) or 2
            
            if adjust_row.get("debit"):
                adjust_row["debit_in_account_currency"] = round_based_on_smallest_currency_fraction(
                    adjust_row["debit"] / adjust_rate,
                    adjust_currency,
                    account_precision
                )
            if adjust_row.get("credit"):
                adjust_row["credit_in_account_currency"] = round_based_on_smallest_currency_fraction(
                    adjust_row["credit"] / adjust_rate,
                    adjust_currency,
                    account_precision
                )
    
    def build(self):
        """Return the built journal entry document."""
        return self.jv


class ServiceInvoice(Document):
    def before_save(self):
        for invoice in self.invoices:
            if frappe.db.exists("Service Invoice Items", {"bill_no": invoice.bill_no, "docstatus": 1}):
                parent_sales_invoice_no = frappe.db.get_value('Service Invoice Items', {"bill_no": invoice.bill_no}, 'parent')
                service_invoice_link = frappe.utils.get_link_to_form("Service Invoice", parent_sales_invoice_no)        
                frappe.throw(f"Bill No {invoice.bill_no} already exists on Sales Invoice {service_invoice_link}")
    
    def on_submit(self):
        """
        Create one Journal Entry per invoice, splitting VAT correctly for
        VAT-inclusive or VAT-exclusive amounts, and linking back to the source row.
        
        This refactored version uses helper classes for better separation of concerns:
        - AmountCalculator: Handles VAT calculations with proper rounding
        - JournalEntryBuilder: Handles multi-currency conversions and line creation
        """
        company = self.get("company") or get_default_company()
        company_currency = get_company_currency(company)
        vat_inclusive = flt(self.vat_inclusive) == 1

        for inv in self.invoices:
            # Get tax details
            tax_detail = get_tax_rate(inv.vat_code)
            tax_rate = flt(tax_detail.get("tax_rate"))
            tax_account = tax_detail.get("tax_account")

            # Calculate net amount
            net = flt(inv.credit) - flt(inv.debit)
            if not net:
                # Nothing to post for this row
                continue

            gross = abs(net)
            is_credit = net > 0  # True if party line is a credit

            # Calculate amounts using AmountCalculator
            calculator = AmountCalculator(
                gross_amount=gross,
                tax_rate=tax_rate,
                account_currency=inv.account_currency,
                vat_inclusive=vat_inclusive
            )
            amounts = calculator.calculate()
            invoice_amount = amounts['invoice_amount']
            vat_amount = amounts['vat_amount']

            # Build journal entry using JournalEntryBuilder
            builder = JournalEntryBuilder(inv, company, company_currency)
            
            # Set header
            multi_currency = bool(
                inv.account_currency and 
                inv.offset_account_currency and 
                (inv.account_currency != company_currency or 
                 inv.offset_account_currency != company_currency)
            )
            builder.set_header(
                naming_series=self.get("naming_series"),
                posting_date=inv.date,
                user_remark=inv.description,
                cheque_no=self.name,
                cheque_date=inv.date,
                multi_currency=multi_currency,
                bill_no=getattr(inv, "bill_no", None),
                bill_date=getattr(inv, "bill_date", None),
                due_date=getattr(inv, "due_date", None),
            )

            # Add party line
            builder.add_party_line(invoice_amount, is_credit)

            # Add offset line
            builder.add_offset_line(
                offset_amount=invoice_amount,
                is_credit=is_credit,
                vat_inclusive=vat_inclusive,
                gross_amount=gross
            )

            # Add VAT line if applicable
            if tax_rate and flt(vat_amount):
                builder.add_vat_line(vat_amount, tax_account, is_credit)

            # Balance the journal entry
            builder.balance_journal_entry()

            # Get the built journal entry
            jv = builder.build()

            # Save and submit
            jv.save()
            jv.submit()

            # Link back to the source row
            frappe.db.set_value("Service Invoice Items", inv.get("name"), "journal_entry", jv.name)

    def on_cancel(self):
        for invoice in self.invoices:
            je_name = frappe.db.get_value('Service Invoice Items', invoice.get('name'), 'journal_entry')
            if frappe.db.exists('Journal Entry', je_name):
                je = frappe.get_doc('Journal Entry', je_name)
                je.cancel()

            
            
@frappe.whitelist()
def generate_reference_id():
    SQL = """ 
    	select 
     		max(reference_id) as last_reference_id
		from `tabService Invoice Items`;
	"""
    invoice = frappe.db.sql( SQL, as_dict=True )    
    latest_reference_id = invoice[0].last_reference_id
    
    if latest_reference_id:
        new_reference_id = int(latest_reference_id) + 1
    else:
        new_reference_id = 1
    
    return new_reference_id

@frappe.whitelist()
def make_reverse_service_invoice_entry(source_name, target_doc=None):
	from frappe.model.mapper import get_mapped_doc

	def post_process(source, target):
		target.reversal_of = source.name

	doclist = get_mapped_doc(
		"Service Invoice",
		source_name,
		{
			"Service Invoice": {"doctype": "Service Invoice", "validation": {"docstatus": ["=", 1]}},
			"Service Invoice Items": {
				"doctype": "Service Invoice Items",
				"field_map": {
					"account_currency": "account_currency",
					"exchange_rate": "exchange_rate",
					"debit_in_account_currency": "credit_in_account_currency",
					"debit": "credit",
					"credit_in_account_currency": "debit_in_account_currency",
					"credit": "debit",
					"user_remark": "user_remark"
				},
			},
		},
		target_doc,
		post_process,
	)

	return doclist

def get_tax_rate(vat_code):
    tax_account = ''
    tax_rate = 0

    if vat_code:
        result = frappe.db.get_value("Item Tax Template Detail", {"parent": vat_code}, ['tax_type', 'tax_rate'])
        if result:
            tax_account, tax_rate = result
    
    tax_detail = {
        "tax_account": tax_account,
        "tax_rate": tax_rate
    }
    
    return tax_detail
