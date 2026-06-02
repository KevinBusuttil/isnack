isnack_register_manual_line_handlers("Sales Invoice Item");

frappe.ui.form.on('Sales Invoice', {
    refresh(frm) {
        // Restrict items.item_code to the Item Groups configured under
        // General Settings → Sales. Applied in refresh (not setup) because
        // ERPNext's selling-controller setup_queries also registers a
        // get_query on items.item_code and would otherwise win.
        isnack_apply_sales_item_group_filter(frm);

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
    },

    conversion_rate(frm) {
        // Currency conversion changed: recompute base fields for every manual line.
        isnack_recalc_manual_lines(frm);
    }
});
