# Copyright (c) 2023, Busuttil Technologies Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from erpnext import get_default_company

class ServiceInvoice(Document):
    def before_save(self):
        for invoice in self.invoices:
            if frappe.db.exists("Service Invoice Items", {"bill_no": invoice.bill_no, "docstatus": 1}):
                parent_sales_invoice_no = frappe.db.get_value('Service Invoice Items', {"bill_no": invoice.bill_no}, 'parent')
                service_invoice_link = frappe.utils.get_link_to_form("Service Invoice", parent_sales_invoice_no)        
                frappe.throw(f"Bill No {invoice.bill_no} already exists on Sales Invoice {service_invoice_link}")
    
    def on_submit(self):
                
        for invoice in self.invoices:
    
            tax_detail = get_tax_rate( invoice.vat_code )

            jv = frappe.new_doc('Journal Entry')
            jv.voucher_type = 'Journal Entry'
            jv.naming_series = self.get("naming_series")
            jv.posting_date = invoice.date
            company = self.get("company") or get_default_company()
            jv.multi_currency = invoice.multi_currency
            jv.company = company
            jv.user_remark = invoice.description
            jv.cheque_no = self.name
            jv.cheque_date = invoice.date
            jv.bill_no = invoice.bill_no
            jv.bill_date = invoice.bill_date
            jv.due_date = invoice.due_date

            # Separate VAT Amount from Invoice Amount
            if self.vat_inclusive == 1:
                # VAT Inclusive
                invoice_amount = invoice.credit / ((tax_detail["tax_rate"] + 100) / 100)
                vat_amount = invoice.credit - invoice_amount
                
                jv.append('accounts', {
                    'account': invoice.account,
                    'party_type' : invoice.party_type,
                    'party' : invoice.party,
                    'credit' : float(invoice.credit),
                    'debit' : float(0),
                    'debit_in_account_currency' : float(0),
                    'credit_in_account_currency' : float(invoice.credit),
                    'cost_center' : invoice.cost_center,
                })
                
                jv.append('accounts', {
                    'account': invoice.offset_account,
                    'credit' : float(0),
                    'debit' : float(invoice_amount),
                    'debit_in_account_currency' : float(invoice_amount),
                    'credit_in_account_currency' : float(0),
                    'cost_center' : invoice.cost_center,
                })
                
                if vat_amount > 0:
                    jv.append('accounts', {
                        'account': tax_detail["tax_account"],
                        'credit' : float(0),
                        'debit' : float(vat_amount),
                        'debit_in_account_currency' : float(vat_amount),
                        'credit_in_account_currency' : float(0),
                        'cost_center' : invoice.cost_center,
                })
            else:
                is_credit = True if (invoice.credit - invoice.debit) >= 0 else False
                # VAT Exclusive
                vat_amount = (invoice.credit - invoice.debit) * ((tax_detail["tax_rate"]) / 100)
                invoice_amount = (invoice.credit - invoice.debit) + vat_amount
                
                jv.append('accounts', {
                    'account': invoice.account,
                    'party_type' : invoice.party_type,
                    'party' : invoice.party,
                    'credit' : float(invoice.credit - invoice.debit + abs(vat_amount)) if is_credit==True else 0,
                    'debit' : float(invoice.debit - invoice.credit + abs(vat_amount)) if is_credit==False else 0,
                    'debit_in_account_currency' : float(invoice.debit - invoice.credit + abs(vat_amount)) if is_credit==False else 0,
                    'credit_in_account_currency' : float(invoice.credit - invoice.debit + abs(vat_amount)) if is_credit==True else 0,
                    'cost_center' : invoice.cost_center,
                })
                
                jv.append('accounts', {
                    'account': invoice.offset_account,
                    'credit' : float(invoice.debit - invoice.credit) if is_credit==False else 0,
                    'debit' : float(invoice.credit - invoice.debit) if is_credit==True else 0,
                    'debit_in_account_currency' : float(invoice.credit - invoice.debit) if is_credit==True else 0,
                    'credit_in_account_currency' : float(invoice.debit - invoice.credit) if is_credit==False else 0,
                    'cost_center' : invoice.cost_center,
                })
                
                if abs(vat_amount) > 0:
                    jv.append('accounts', {
                        'account': tax_detail["tax_account"],
                        'credit' : float(abs(vat_amount)) if is_credit==False else 0,
                        'debit' : float(abs(vat_amount)) if is_credit==True else 0,
                        'debit_in_account_currency' : float(vat_amount) if is_credit==True else 0,
                        'credit_in_account_currency' : float(-vat_amount) if is_credit==False else 0,
                        'cost_center' : invoice.cost_center,
                    })

            jv.save()
            jv.submit()

            frappe.db.set_value('Service Invoice Items', invoice.get('name'), 'journal_entry', jv.name)      

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