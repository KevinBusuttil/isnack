# Copyright (c) 2023, Busuttil Technologies Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from erpnext import get_default_company, get_company_currency

class ServiceInvoice(Document):
    def before_save(self):
        for invoice in self.invoices:
            if frappe.db.exists("Service Invoice Items", {"bill_no": invoice.bill_no, "docstatus": 1}):
                parent_sales_invoice_no = frappe.db.get_value('Service Invoice Items', {"bill_no": invoice.bill_no}, 'parent')
                service_invoice_link = frappe.utils.get_link_to_form("Service Invoice", parent_sales_invoice_no)        
                frappe.throw(f"Bill No {invoice.bill_no} already exists on Sales Invoice {service_invoice_link}")
    
    def on_submit(self):
        """Create one Journal Entry per invoice, splitting VAT correctly for
        VAT-inclusive or VAT-exclusive amounts, and linking back to the source row.
        """
        import json
        from frappe.utils import flt, round_based_on_smallest_currency_fraction

        from erpnext.setup.utils import get_exchange_rate

        def add_row(jv, *, account, cost_center=None, party_type=None, party=None,
                    debit_acc=None, credit_acc=None, debit=None, credit=None):
            """Append a clean JE line. Prefer *_in_account_currency fields."""
            row = {"account": account}
            if cost_center:
                row["cost_center"] = cost_center
            if party_type and party:
                row["party_type"] = party_type
                row["party"] = party
            # In multi-currency scenarios, ERPNext prefers *_in_account_currency.
            if debit_acc is not None:
                row["debit_in_account_currency"] = flt(debit_acc)
            if credit_acc is not None:
                row["credit_in_account_currency"] = flt(credit_acc)
            # In single-currency cases, these are fine too (optional).
            if debit is not None:
                row["debit"] = flt(debit)
            if credit is not None:
                row["credit"] = flt(credit)
            jv.append("accounts", row)

        company = self.get("company") or get_default_company()
        company_currency = get_company_currency(company)

        vat_inclusive = flt(self.vat_inclusive) == 1

        for inv in self.invoices:
            account_exchange_rate = get_exchange_rate(inv.account_currency, company_currency, inv.date)
            offset_account_exchange_rate = get_exchange_rate(inv.offset_account_currency, company_currency, inv.date)

            # print(f'A: {account_exchange_rate} O: {offset_account_exchange_rate}')

            # --- Inputs & basics -------------------------------------------------
            tax_detail = get_tax_rate(inv.vat_code)  # expects {"tax_rate": x, "tax_account": y}
            tax_rate = flt(tax_detail.get("tax_rate"))
            tax_account = tax_detail.get("tax_account")

            net = flt(inv.credit) - flt(inv.debit)  # +ve => credit; -ve => debit
            if not net:
                # Nothing to post for this row.
                continue

            gross = abs(net)
            sign_credit = net > 0  # True if party line is a credit

            # --- Build the Journal Entry header ---------------------------------
            jv = frappe.new_doc("Journal Entry")
            jv.voucher_type = "Journal Entry"
            jv.naming_series = self.get("naming_series")
            jv.posting_date = inv.date
            jv.company = company
            jv.multi_currency = bool(inv.account_currency and inv.offset_account_currency and (inv.account_currency != company_currency or (inv.offset_account_currency != company_currency)))
            jv.user_remark = inv.description
            jv.cheque_no = self.name
            jv.cheque_date = inv.date

            # Optional metadata (set only if present)
            if getattr(inv, "bill_no", None):
                jv.bill_no = inv.bill_no
            if getattr(inv, "bill_date", None):
                jv.bill_date = inv.bill_date
            if getattr(inv, "due_date", None):
                jv.due_date = inv.due_date

            # --- Amount composition ---------------------------------------------
            if vat_inclusive:
                divisor = (tax_rate + 100.0) / 100.0 if tax_rate else 1.0
                invoice_amount = gross / divisor
                vat_amount = gross - invoice_amount
            else:
                vat_amount = gross * (tax_rate / 100.0) if tax_rate else 0.0
                invoice_amount = gross + vat_amount  # total on the party line

            # --- Lines -----------------------------------------------------------
            # 1) Party line (supplier / customer) on inv.account
            if sign_credit:
                # Credit party
                add_row(
                    jv,
                    account=inv.account,
                    party_type=getattr(inv, "party_type", None),
                    party=getattr(inv, "party", None),
                    cost_center=inv.cost_center,
                    credit_acc=invoice_amount if vat_inclusive else invoice_amount,  # same var name for clarity
                )
            else:
                # Debit party
                add_row(
                    jv,
                    account=inv.account,
                    party_type=getattr(inv, "party_type", None),
                    party=getattr(inv, "party", None),
                    cost_center=inv.cost_center,
                    debit_acc=invoice_amount if vat_inclusive else invoice_amount,
                )

            # 2) Offset line (inv.offset_account) for the net (excl. VAT if exclusive, else net of VAT)
            offset_amount = (invoice_amount if vat_inclusive else gross)
            if inv.offset_account_currency and inv.account_currency and inv.offset_account_currency != inv.account_currency:
                # guard against zero/None exchange rates
                acc_rate   = flt(account_exchange_rate) or 1
                off_rate   = flt(offset_account_exchange_rate) or 1
                factor     = acc_rate / off_rate
                offset_amount = offset_amount * factor

            # currency rounding for the offset account currency
            precision = frappe.get_precision(
                "Journal Entry Account",
                "debit_in_account_currency",
                currency=inv.offset_account_currency,
            ) or 2

            offset_amount = round_based_on_smallest_currency_fraction(
                offset_amount, inv.offset_account_currency, precision
            )

            if sign_credit:
                # Credit to party means offset is a debit
                add_row(
                    jv,
                    account=inv.offset_account,
                    cost_center=inv.cost_center,
                    debit_acc=offset_amount,
                )
            else:
                # Debit to party means offset is a credit
                add_row(
                    jv,
                    account=inv.offset_account,
                    cost_center=inv.cost_center,
                    credit_acc=offset_amount,
                )

            # 3) VAT line (if any)
            if tax_rate and flt(vat_amount):
                if sign_credit:
                    # Party credited -> VAT is a debit
                    add_row(
                        jv,
                        account=tax_account,
                        cost_center=inv.cost_center,
                        debit_acc=vat_amount,
                    )
                else:
                    # Party debited -> VAT is a credit
                    add_row(
                        jv,
                        account=tax_account,
                        cost_center=inv.cost_center,
                        credit_acc=vat_amount,
                    )

            # --- Debug logging (toggle with `frappe.flags.debug = True`) --------
            # print("BEFORE SAVE (valid dict):")
            # print(json.dumps(jv.get_valid_dict(), indent=2, default=str))

            # Persist & submit
            jv.save()
            # print("AFTER SAVE (valid dict):")
            # print(json.dumps(jv.get_valid_dict(), indent=2, default=str))

            jv.submit()

            # Link back to the source row
            frappe.db.set_value("Service Invoice Items", inv.get("name"), "journal_entry", jv.name)

    # def on_submit(self):
                
    #     for invoice in self.invoices:
    
    #         tax_detail = get_tax_rate( invoice.vat_code )

    #         jv = frappe.new_doc('Journal Entry')
    #         jv.voucher_type = 'Journal Entry'
    #         jv.naming_series = self.get("naming_series")
    #         jv.posting_date = invoice.date
    #         company = self.get("company") or get_default_company()
    #         jv.multi_currency = invoice.multi_currency
    #         jv.company = company
    #         jv.user_remark = invoice.description
    #         jv.cheque_no = self.name
    #         jv.cheque_date = invoice.date
    #         jv.bill_no = invoice.bill_no
    #         jv.bill_date = invoice.bill_date
    #         jv.due_date = invoice.due_date

    #         # Separate VAT Amount from Invoice Amount
    #         if self.vat_inclusive == 1:
    #             # VAT Inclusive
    #             invoice_amount = invoice.credit / ((tax_detail["tax_rate"] + 100) / 100)
    #             vat_amount = invoice.credit - invoice_amount
                
    #             jv.append('accounts', {
    #                 'account': invoice.account,
    #                 'party_type' : invoice.party_type,
    #                 'party' : invoice.party,
    #                 'credit' : float(invoice.credit),
    #                 'debit' : float(0),
    #                 'debit_in_account_currency' : float(0),
    #                 'credit_in_account_currency' : float(invoice.credit),
    #                 'cost_center' : invoice.cost_center,
    #             })
                
    #             jv.append('accounts', {
    #                 'account': invoice.offset_account,
    #                 'credit' : float(0),
    #                 'debit' : float(invoice_amount),
    #                 'debit_in_account_currency' : float(invoice_amount),
    #                 'credit_in_account_currency' : float(0),
    #                 'cost_center' : invoice.cost_center,
    #             })
                
    #             if vat_amount > 0:
    #                 jv.append('accounts', {
    #                     'account': tax_detail["tax_account"],
    #                     'credit' : float(0),
    #                     'debit' : float(vat_amount),
    #                     'debit_in_account_currency' : float(vat_amount),
    #                     'credit_in_account_currency' : float(0),
    #                     'cost_center' : invoice.cost_center,
    #             })
    #         else:
    #             is_credit = True if (invoice.credit - invoice.debit) >= 0 else False
    #             # VAT Exclusive
    #             vat_amount = (invoice.credit - invoice.debit) * ((tax_detail["tax_rate"]) / 100)
    #             invoice_amount = (invoice.credit - invoice.debit) + vat_amount

    #             jv.append('accounts', {
    #                 'account': invoice.account,
    #                 'party_type' : invoice.party_type,
    #                 'party' : invoice.party,
    #                 #'credit' : float(invoice.credit - invoice.debit + abs(vat_amount)) if is_credit==True else 0,
    #                 #'debit' : float(invoice.debit - invoice.credit + abs(vat_amount)) if is_credit==False else 0,
    #                 'debit_in_account_currency' : float(invoice.debit - invoice.credit + abs(vat_amount)) if is_credit==False else 0,
    #                 'credit_in_account_currency' : float(invoice.credit - invoice.debit + abs(vat_amount)) if is_credit==True else 0,
    #                 'cost_center' : invoice.cost_center,
    #             })
                
    #             jv.append('accounts', {
    #                 'account': invoice.offset_account,
    #                 #'credit' : float(invoice.debit - invoice.credit) if is_credit==False else 0,
    #                 #'debit' : float(invoice.credit - invoice.debit) if is_credit==True else 0,
    #                 'debit_in_account_currency' : float(invoice.credit - invoice.debit) if is_credit==True else 0,
    #                 'credit_in_account_currency' : float(invoice.debit - invoice.credit) if is_credit==False else 0,
    #                 'cost_center' : invoice.cost_center,
    #             })
                
    #             if abs(vat_amount) > 0:
    #                 jv.append('accounts', {
    #                     'account': tax_detail["tax_account"],
    #                     #'credit' : float(abs(vat_amount)) if is_credit==False else 0,
    #                     #'debit' : float(abs(vat_amount)) if is_credit==True else 0,
    #                     'debit_in_account_currency' : float(vat_amount) if is_credit==True else 0,
    #                     'credit_in_account_currency' : float(-vat_amount) if is_credit==False else 0,
    #                     'cost_center' : invoice.cost_center,
    #                 })
    #         import json
    #         print('BEFORE SAVE: json dumps:')                    
    #         print(json.dumps(jv.get_valid_dict(), indent=2, default=str))
    #         jv.save()
    #         print('AFTER SAVE: json dumps:')                    
    #         print(json.dumps(jv.get_valid_dict(), indent=2, default=str))
    #         jv.submit()

    #         frappe.db.set_value('Service Invoice Items', invoice.get('name'), 'journal_entry', jv.name)      

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
        tax_account, tax_rate = frappe.db.get_value("Item Tax Template Detail", {"parent": vat_code}, ['tax_type', 'tax_rate'])
    
    tax_detail = {
        "tax_account": tax_account,
        "tax_rate": tax_rate
    }
    
    return tax_detail