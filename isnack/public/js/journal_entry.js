// Copyright (c) 2024, Busuttil Technologies Limited
// License: MIT
// This file implements a fix for multi-currency Journal Entry exchange rate handling
// 
// Issue: When adding a new row in a Journal Entry, the accounts_add function
// incorrectly copies the exchange_rate from an existing row that has account, 
// party, and party_type set. This causes problems when the new row has a 
// different currency account.
//
// Fix: Override accounts_add to prevent copying exchange_rate from other rows.
// The exchange rate should remain at its default value of 1 and be properly
// fetched when the user selects the account, based on that account's currency.

function update_multi_currency(frm) {
	const company_currency = frm.doc.company_currency || frappe.defaults.get_default("currency");
	if (!company_currency) {
		return;
	}

	const has_foreign_currency = (frm.doc.accounts || []).some((row) => {
		return row.account_currency && row.account_currency !== company_currency;
	});

	frm.set_value("multi_currency", has_foreign_currency ? 1 : 0);
}

function set_row_account_currency(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);

	if (!row.account) {
		update_multi_currency(frm);
		return;
	}

	if (row.account_currency) {
		update_multi_currency(frm);
		return;
	}

	return frappe.db.get_value("Account", row.account, "account_currency").then((r) => {
		if (r.message && r.message.account_currency) {
			return frappe.model.set_value(cdt, cdn, "account_currency", r.message.account_currency);
		}
	}).then(() => {
		update_multi_currency(frm);
	});
}

frappe.ui.form.on('Journal Entry', {
	accounts_remove: function(frm) {
		update_multi_currency(frm);
	}
});

frappe.ui.form.on('Journal Entry Account', {
	accounts_add: function(frm, cdt, cdn) {
		var row = frappe.get_doc(cdt, cdn);
		
		// Copy account, party, and party_type from existing rows if they exist
		// BUT DO NOT copy exchange_rate - it should be determined by the actual
		// account currency selected in this row
		$.each(frm.doc.accounts, function(i, d) {
			if (d.account && d.party && d.party_type) {
				row.account = d.account;
				row.party = d.party;
				row.party_type = d.party_type;
				console.log("Copied account details from existing row:", d);
				// REMOVED: row.exchange_rate = d.exchange_rate;
				// This line was causing the bug - exchange rate should not be
				// copied from other rows as they may have different currencies
				return false; // Break after copying from first matching row
			}
		});
		
		// Set default cost center if specified
		if (frm.doc.cost_center) {
			row.cost_center = frm.doc.cost_center;
		}
		
		// Initialize exchange_rate to 1 (default for base currency)
		// This will be automatically updated when the user selects an account
		// based on that account's currency via the set_exchange_rate function
		frappe.model.set_value(cdt, cdn, 'exchange_rate', 1);
		update_multi_currency(frm);
	},
	account: function(frm, cdt, cdn) {
		return set_row_account_currency(frm, cdt, cdn);
	},
	party_type: function(frm, cdt, cdn) {
		update_multi_currency(frm);
	},
	party: function(frm, cdt, cdn) {
		return set_row_account_currency(frm, cdt, cdn);
	}
});