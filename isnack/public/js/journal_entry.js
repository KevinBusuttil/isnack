// Copyright (c) 2024, Busuttil Technologies Limited
// License: MIT
// This file implements a fix for multi-currency Journal Entry exchange rate handling

function update_multi_currency(frm) {
	const company_currency = frm.doc.company_currency || frappe.defaults.get_default("currency");
	if (!company_currency) {
		return;
	}

	const has_foreign_currency = (frm.doc.accounts || []).some((row) => {
		return row.account_currency && row.account_currency !== company_currency;
	});

	// Only update if value actually changes to prevent cascading events
	if (frm.doc.multi_currency !== (has_foreign_currency ? 1 : 0)) {
		frm.set_value("multi_currency", has_foreign_currency ? 1 : 0);
	}
}

erpnext.journal_entry.set_account_details = function(frm, dt, dn) {
	var d = locals[dt][dn];
	if (d.account) {
		if (!frm.doc.company) frappe.throw(__("Please select Company first"));
		if (!frm.doc.posting_date) frappe.throw(__("Please select Posting Date first"));

		return frappe.call({
			method: "erpnext.accounts.doctype.journal_entry.journal_entry.get_account_details_and_party_type",
			args: {
				account: d.account,
				date: frm.doc.posting_date,
				company: frm.doc.company,
				debit: flt(d.debit_in_account_currency),
				credit: flt(d.credit_in_account_currency),
			},
			callback: function (r) {
				if (r.message) {
					$.extend(d, r.message);
					// Update multi_currency after account_currency is populated by server
					update_multi_currency(frm);
					erpnext.journal_entry.set_amount_on_last_row(frm, dt, dn);
					erpnext.journal_entry.set_debit_credit_in_company_currency(frm, dt, dn);
					refresh_field("accounts");
				}
			},
		});
	}
}

frappe.ui.form.on('Journal Entry', {
	accounts_remove: function(frm) {
		update_multi_currency(frm);
	}
});

frappe.ui.form.on('Journal Entry Account', {
	// Trigger when account_currency changes (after server populates it or set manually)
	account_currency: function(frm, cdt, cdn) {
		update_multi_currency(frm);
	},
	
	party_type: function(frm, cdt, cdn) {
		update_multi_currency(frm);
	},
	
	party: function(frm, cdt, cdn) {
		update_multi_currency(frm);
	}
});