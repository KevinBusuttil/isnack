frappe.ui.form.on('Sales Invoice', {
    refresh(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(
                __('Traceability Report'),
                function () {
                    frappe.set_route('query-report', 'Customs Export Traceability Report', {
                        sales_invoice: frm.doc.name,
                        customer: frm.doc.customer,
                        company: frm.doc.company
                    });
                },
                __('View')
            );
        }
    }
});
