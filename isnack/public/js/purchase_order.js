frappe.ui.form.on('Purchase Order', {
    refresh: function(frm) {
		frm.set_query("item_code", "items", (doc, cdt, cdn) => {
			return {
				query: "isnack.utils.get_items_filtered_by_supplier",
                filters: {
                    supplier: doc.supplier
                }
			};
		});
    }
});
