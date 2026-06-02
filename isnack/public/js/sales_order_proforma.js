isnack_register_manual_line_handlers("Sales Order Item");

frappe.ui.form.on('Sales Order', {
    refresh(frm) {
        // Restrict items.item_code to the Item Groups configured under
        // General Settings → Sales. Applied in refresh (not setup) because
        // ERPNext's selling-controller setup_queries also registers a
        // get_query on items.item_code and would otherwise win.
        isnack_apply_sales_item_group_filter(frm);

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
    },

    conversion_rate(frm) {
        // Currency conversion changed: recompute base fields for every manual line.
        isnack_recalc_manual_lines(frm);
    }
});
