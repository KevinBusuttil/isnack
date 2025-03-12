frappe.ui.form.on('Sales Order', {
    refresh(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Proforma Invoice'), () => {
                frappe.call({
                    method: "isnack.isnack.doctype.proforma_sales_invoice.proforma_sales_invoice.create_proforma_sales_invoice",
                    args: { sales_order_name: frm.doc.name },
                    callback(r) {
                        if (r.message) {
                            frm.print_doc("Proforma Sales Invoice");
                        }
                    }
                });
            }, __("Create"));
        }
    }
});
