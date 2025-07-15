frappe.ui.form.on('Purchase Order', {
	refresh(frm) {
		set_item_code_query(frm);
	},

	// if the Supplier is changed, refresh the query (only matters when the
	// asset flag is *not* ticked)
	supplier(frm) {
		set_item_code_query(frm);
	},

	// if the new checkbox is toggled, switch the query immediately
	custom_asset_purchasing(frm) {
		set_item_code_query(frm);
	}
});

function set_item_code_query(frm) {
	frm.set_query('item_code', 'items', () => {

		// 1. Asset PO – ignore Supplier and show all asset items
		if (frm.doc.custom_asset_purchasing) {
			return {
				filters: {
					is_fixed_asset: 1,   // standard ERPNext flag for asset items
					is_purchase_item: 1, // still must be purchasable
					disabled: 0          // hide disabled items
				}
			};
		}

		// 2. Normal PO – keep your existing supplier‑based filter
		return {
			query:  'isnack.utils.get_items_filtered_by_supplier',
			filters: { supplier: frm.doc.supplier }
		};
	});
}
