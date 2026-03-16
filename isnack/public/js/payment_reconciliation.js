// Copyright (c) 2026, Busuttil Technologies Limited
// License: MIT
// Client-side script for Payment Reconciliation custom features

frappe.ui.form.on('Payment Reconciliation', {
	suppress_exchange_gain_loss(frm) {
		// If allocation table already has rows, clear it so user re-allocates
		// with the new suppress setting applied server-side
		if (frm.doc.allocation && frm.doc.allocation.length > 0) {
			frm.clear_table('allocation');
			frm.refresh_field('allocation');
			frappe.msgprint(
				__('Allocation cleared. Please re-run Allocate Entries to apply the updated exchange gain/loss setting.')
			);
		}
	}
});
