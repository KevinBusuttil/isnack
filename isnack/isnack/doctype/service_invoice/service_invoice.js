// Copyright (c) 2023, Busuttil Technologies Ltd and contributors
// For license information, please see license.txt

frappe.provide("erpnext.accounts");
frappe.provide("isnack.accounts.service_invoice")

frappe.ui.form.on('Service Invoice', {
	onload: function(frm) {
		frm.set_query("account", "invoices", function(doc){
			return {
				filters: {
					"company": doc.company,
					"is_group": 0,
					"do_not_manual_entry": 0,
				}
			}
		});
		frm.set_query("offset_account", "invoices", function(doc){
			return {
				filters: {
					"company": doc.company,
					"is_group": 0,
					"do_not_manual_entry": 0,
				}
			}
		});
		frm.set_query("party_type", "invoices", function(){
			return {
				"filters": [
					["DocType", "name", "in", ["Supplier", "Customer"]]
				]
			}
		});
		frm.set_query("cost_center", "invoices", function(doc) {
			return {
				filters: {
					"company": doc.company,
					"is_group": 0
				}
			}
		});
		frm.set_query("vat_code", "invoices", function(doc) {
			return {
				filters: {
					"company": doc.company,
				}
			}
		});
	},
	refresh: function(frm, cdt, cdn) {
		if(frm.doc.docstatus==1) {
			frm.add_custom_button(__('Reverse Service Invoice'), function() {
				return isnack.accounts.service_invoice.reverse_service_invoice_entry(frm);
			}, __('Actions'));
		}
	},
	company: function(frm) {
		frappe.call({
			method: "frappe.client.get_value",
			args: {
				doctype: "Company",
				filters: {"name": frm.doc.company},
				fieldname: "cost_center"
			},
			callback: function(r){
				if(r.message){
					$.each(frm.doc.invoices || [], function(i, jvd) {
						frappe.model.set_value(jvd.doctype, jvd.name, "cost_center", r.message.cost_center);
					});
				}
			}
		});

		erpnext.accounts.dimensions.update_dimension(frm, frm.doctype);
	},

});

isnack.accounts.service_invoice = {
	reverse_service_invoice_entry: function() {
		frappe.model.open_mapped_doc({
			method: "isnack.isnack.doctype.service_invoice.service_invoice.make_reverse_service_invoice_entry",
			frm: cur_frm
		})
	},
}

frappe.ui.form.on('Service Invoice Items', {
	party: function(frm, cdt, cdn) {
		var invoice = frappe.get_doc(cdt, cdn);
		if(invoice.party_type && invoice.party) {
			if(!frm.doc.company) frappe.throw(__("Please select Company"));
			return frm.call({
				method: "erpnext.accounts.doctype.journal_entry.journal_entry.get_party_account_and_balance",
				child: invoice,
				args: {
					company: frm.doc.company,
					party_type: invoice.party_type,
					party: invoice.party,
					cost_center: invoice.cost_center
				}
			});
		}
	},
	invoice_add(frm, cdt, cdn) {
		var invoice = frappe.get_doc(cdt, cdn);
		frappe.call({
			method: 'isnack.isnack.doctype.service_invoice.service_invoice.generate_reference_id',
			callback: function(r) {
				invoice.reference_id = r.message;
       			frm.refresh_field('invoices');
			}
		});
	}
})