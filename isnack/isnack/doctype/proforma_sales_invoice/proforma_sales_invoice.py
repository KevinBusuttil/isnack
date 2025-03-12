# Copyright (c) 2025, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ProformaSalesInvoice(Document):
	pass

@frappe.whitelist()
def create_proforma_sales_invoice(sales_order_name):
    if frappe.db.exists("Sales Order", sales_order_name):
        sales_order = frappe.get_doc("Sales Order", sales_order_name)

		# Check if a Proforma already exists for this Sales Order
        existing_invoice = frappe.db.exists("Proforma Sales Invoice", {
			"sales_order": sales_order_name,
		})

        if existing_invoice:
			# Return existing Proforma Invoice
            return existing_invoice
        else:
            proforma_invoice = frappe.new_doc("Proforma Sales Invoice")
            proforma_invoice.sales_order = sales_order.name
            proforma_invoice.customer = sales_order.customer
            proforma_invoice.last_printed_on = frappe.utils.today()
			
            proforma_invoice.insert(ignore_permissions=True)
			
            return proforma_invoice.name