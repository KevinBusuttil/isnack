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
    },

    conversion_rate(frm) {
        // Currency conversion changed: recompute base fields for every manual line.
        (frm.doc.items || []).forEach((row) => {
            if (flt(row.custom_manual_price_list_rate)) {
                isnack_apply_manual_line_discount(frm, row.doctype, row.name, "qty");
            }
        });
    }
});

frappe.ui.form.on("Sales Order Item", {
    custom_manual_price_list_rate(frm, cdt, cdn) {
        isnack_apply_manual_line_discount(frm, cdt, cdn, "price");
    },

    custom_manual_discount_percentage(frm, cdt, cdn) {
        isnack_apply_manual_line_discount(frm, cdt, cdn, "percentage");
    },

    custom_manual_discount_amount(frm, cdt, cdn) {
        isnack_apply_manual_line_discount(frm, cdt, cdn, "amount");
    },

    qty(frm, cdt, cdn) {
        isnack_apply_manual_line_discount(frm, cdt, cdn, "qty");
    },

    item_code(frm, cdt, cdn) {
        // Let ERPNext fetch item details first, then initialise the manual
        // price list rate from the standard rate if it has not been set yet.
        frappe.after_ajax(() => {
            const updated_row = locals[cdt][cdn];

            if (
                updated_row &&
                flt(updated_row.price_list_rate) &&
                !flt(updated_row.custom_manual_price_list_rate)
            ) {
                updated_row.custom_manual_price_list_rate = flt(
                    updated_row.price_list_rate,
                    precision("custom_manual_price_list_rate", updated_row)
                );

                frm.refresh_field("items");
            }
        });
    }
});

function isnack_apply_manual_line_discount(frm, cdt, cdn, source) {
    // Guard against re-entrancy while we write standard ERPNext fields.
    if (frm.__isnack_manual_discount_running) {
        return;
    }

    const row = locals[cdt][cdn];

    if (!row) {
        return;
    }

    const manual_price = flt(row.custom_manual_price_list_rate);
    const qty = flt(row.qty) || 0;
    const conversion_rate = flt(frm.doc.conversion_rate) || 1;

    // Blank or zero manual price: do nothing.
    if (!manual_price) {
        return;
    }

    frm.__isnack_manual_discount_running = true;

    try {
        let manual_discount_percentage = flt(row.custom_manual_discount_percentage);
        let manual_discount_amount = flt(row.custom_manual_discount_amount);
        let discount_percentage = 0;
        let discount_amount = 0;
        let rate = manual_price;

        if (source === "percentage") {
            // Entering a percentage clears the amount (mutual exclusivity).
            manual_discount_amount = 0;
            row.custom_manual_discount_amount = 0;

            if (manual_discount_percentage < 0) {
                manual_discount_percentage = 0;
                row.custom_manual_discount_percentage = 0;
            }

            if (manual_discount_percentage > 100) {
                manual_discount_percentage = 100;
                row.custom_manual_discount_percentage = 100;
            }

            discount_percentage = flt(
                manual_discount_percentage,
                precision("discount_percentage", row)
            );

            discount_amount = flt(
                manual_price * discount_percentage / 100,
                precision("discount_amount", row)
            );

            rate = manual_price - discount_amount;
        }

        else if (source === "amount") {
            // Entering an amount clears the percentage (mutual exclusivity).
            manual_discount_percentage = 0;
            row.custom_manual_discount_percentage = 0;

            if (manual_discount_amount < 0) {
                manual_discount_amount = 0;
                row.custom_manual_discount_amount = 0;
            }

            if (manual_discount_amount > manual_price) {
                manual_discount_amount = manual_price;
                row.custom_manual_discount_amount = manual_price;
            }

            discount_percentage = 0;
            discount_amount = flt(
                manual_discount_amount,
                precision("discount_amount", row)
            );

            rate = manual_price - discount_amount;
        }

        else {
            // source is "price" or "qty": re-apply the active discount method.
            if (manual_discount_percentage > 0) {
                if (manual_discount_percentage > 100) {
                    manual_discount_percentage = 100;
                    row.custom_manual_discount_percentage = 100;
                }

                discount_percentage = flt(
                    manual_discount_percentage,
                    precision("discount_percentage", row)
                );

                discount_amount = flt(
                    manual_price * discount_percentage / 100,
                    precision("discount_amount", row)
                );

                rate = manual_price - discount_amount;
            }

            else if (manual_discount_amount > 0) {
                if (manual_discount_amount > manual_price) {
                    manual_discount_amount = manual_price;
                    row.custom_manual_discount_amount = manual_price;
                }

                discount_percentage = 0;
                discount_amount = flt(
                    manual_discount_amount,
                    precision("discount_amount", row)
                );

                rate = manual_price - discount_amount;
            }
        }

        rate = flt(rate, precision("rate", row));

        // Write the standard ERPNext fields directly so ERPNext's own
        // controller handlers do not reverse-calculate the discount.
        row.price_list_rate = flt(manual_price, precision("price_list_rate", row));
        row.base_price_list_rate = flt(
            row.price_list_rate * conversion_rate,
            precision("base_price_list_rate", row)
        );

        row.discount_percentage = discount_percentage;
        row.discount_amount = discount_amount;

        // Clear margin fields to prevent Price List Rate + Margin logic interfering.
        row.margin_type = "";
        row.margin_rate_or_amount = 0;
        row.rate_with_margin = 0;
        row.base_rate_with_margin = 0;

        row.rate = rate;
        row.base_rate = flt(rate * conversion_rate, precision("base_rate", row));

        row.amount = flt(rate * qty, precision("amount", row));
        row.base_amount = flt(row.amount * conversion_rate, precision("base_amount", row));

        row.net_rate = rate;
        row.base_net_rate = row.base_rate;

        row.net_amount = row.amount;
        row.base_net_amount = row.base_amount;

        frm.dirty();
        frm.refresh_field("items");

        if (frm.cscript && frm.cscript.calculate_taxes_and_totals) {
            frm.cscript.calculate_taxes_and_totals();
        }
    }

    finally {
        frm.__isnack_manual_discount_running = false;
    }
}
