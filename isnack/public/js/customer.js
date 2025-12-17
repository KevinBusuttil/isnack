frappe.ui.form.on('Customer', {
	refresh(frm) {
		if (!frm.doc.__islocal) {
			// custom buttons

			frm.add_custom_button(
				__("Discount Rules"),
				function () {
                    frappe.set_route("List", "Customer Discount Rules", { customer: frm.doc.name });
				},
				__("Create")
			);
        }

	},
});
