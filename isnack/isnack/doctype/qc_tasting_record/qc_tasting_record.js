frappe.ui.form.on('QC Tasting Record', {
	setup(frm) {
		frm.set_query('batch_no', function() {
			return {
				filters: { item: frm.doc.item_code }
			};
		});
	},
	item_code(frm) {
		// Clear stale batch when item changes
		frm.set_value('batch_no', '');
	}
});
