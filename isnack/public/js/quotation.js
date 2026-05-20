isnack_register_manual_line_handlers("Quotation Item");

frappe.ui.form.on('Quotation', {
    conversion_rate(frm) {
        // Currency conversion changed: recompute base fields for every manual line.
        isnack_recalc_manual_lines(frm);
    }
});
