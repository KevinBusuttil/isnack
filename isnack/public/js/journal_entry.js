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

frappe.ui.form.on('Journal Entry Account', {
	accounts_add: function(frm, cdt, cdn) {
		var row = frappe.get_doc(cdt, cdn);
		row.exchange_rate = 1;
		
		// Copy account, party, and party_type from existing rows if they exist
		// BUT DO NOT copy exchange_rate - it should be determined by the actual
		// account currency selected in this row
		$.each(frm.doc.accounts, function(i, d) {
			if (d.account && d.party && d.party_type) {
				row.account = d.account;
				row.party = d.party;
				row.party_type = d.party_type;
				// REMOVED: row.exchange_rate = d.exchange_rate;
				// This line was causing the bug - exchange rate should not be
				// copied from other rows as they may have different currencies
			}
		});
		
		// Set default cost center if specified
		if (frm.doc.cost_center) {
			row.cost_center = frm.doc.cost_center;
		}
		
		// Refresh the field to ensure UI updates
		frappe.model.set_value(cdt, cdn, 'exchange_rate', row.exchange_rate);
	}
});
