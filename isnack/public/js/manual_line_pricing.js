// Shared manual line pricing/discount logic for Isnack selling transactions
// (Sales Order, Quotation, Sales Invoice).
//
// Users enter a manual Price List Rate plus either a discount percentage or a
// discount amount; these are written into the standard ERPNext fields so the
// final rate is shown immediately without ERPNext reverse-calculating odd
// compounded discounts from auto-applied pricing rules.
//
// Loaded via app_include_js; helpers are attached to `window` so the
// separately-bundled per-doctype scripts can use them.

// Run `fn` once all pending ERPNext ajax requests (get_item_details,
// apply_pricing_rule, ...) have settled, so our writes are never clobbered
// by a late server response. Falls back to a timeout if the helper is absent.
window.isnack_after_ajax = function (fn) {
    if (window.frappe && typeof frappe.after_ajax === "function") {
        frappe.after_ajax(fn);
    } else {
        setTimeout(fn, 0);
    }
};

// Initialise the manual price list rate from the standard price_list_rate
// that ERPNext fetched for the item, when the user has not set one yet.
window.isnack_init_manual_price = function (frm, cdt, cdn) {
    const row = locals[cdt] && locals[cdt][cdn];
    if (!row) {
        return;
    }

    if (flt(row.price_list_rate) && !flt(row.custom_manual_price_list_rate)) {
        row.custom_manual_price_list_rate = flt(
            row.price_list_rate,
            precision("custom_manual_price_list_rate", row)
        );
        frm.refresh_field("items");
    }
};

window.isnack_apply_manual_line_discount = function (frm, cdt, cdn, force) {
    // Compute immediately for instant feedback...
    isnack_compute_manual_line(frm, cdt, cdn, force);

    // ...then re-assert once any ERPNext async pricing/item-details call has
    // settled, so the manual values are always the final word on the row.
    isnack_after_ajax(() => {
        if (locals[cdt] && locals[cdt][cdn]) {
            isnack_compute_manual_line(frm, cdt, cdn, false);
        }
    });
};

window.isnack_compute_manual_line = function (frm, cdt, cdn, force) {
    // Guard against re-entrancy while we write standard ERPNext fields.
    if (frm.__isnack_manual_discount_running) {
        return;
    }

    const row = locals[cdt] && locals[cdt][cdn];

    if (!row) {
        return;
    }

    let manual_price = flt(row.custom_manual_price_list_rate);

    // If the manual price has not been entered/initialised yet, adopt the
    // standard price list rate that ERPNext fetched for the item.
    if (!manual_price) {
        manual_price = flt(row.price_list_rate);
        if (manual_price) {
            row.custom_manual_price_list_rate = flt(
                manual_price,
                precision("custom_manual_price_list_rate", row)
            );
        }
    }

    // Blank or zero manual price: nothing to compute yet.
    if (!manual_price) {
        return;
    }

    const raw_manual_percentage = flt(row.custom_manual_discount_percentage);
    const raw_manual_amount = flt(row.custom_manual_discount_amount);
    const standard_price = flt(row.price_list_rate);

    // For implicit triggers (qty, item_code, conversion rate, async re-assert)
    // only take over the standard fields when the manual layer is actually
    // engaged. This leaves ERPNext pricing rules intact when the user has not
    // entered a manual discount or changed the price.
    const price_changed =
        standard_price &&
        flt(manual_price, precision("price_list_rate", row)) !==
            flt(standard_price, precision("price_list_rate", row));
    const engaged =
        raw_manual_percentage > 0 || raw_manual_amount > 0 || price_changed;

    if (!force && !engaged) {
        return;
    }

    frm.__isnack_manual_discount_running = true;

    try {
        const qty = flt(row.qty) || 0;
        const conversion_rate = flt(frm.doc.conversion_rate) || 1;

        let manual_discount_percentage = raw_manual_percentage;
        let manual_discount_amount = raw_manual_amount;

        // Clamp manual inputs to sane bounds.
        if (manual_discount_percentage < 0) {
            manual_discount_percentage = 0;
            row.custom_manual_discount_percentage = 0;
        }
        if (manual_discount_percentage > 100) {
            manual_discount_percentage = 100;
            row.custom_manual_discount_percentage = 100;
        }
        if (manual_discount_amount < 0) {
            manual_discount_amount = 0;
            row.custom_manual_discount_amount = 0;
        }
        if (manual_discount_amount > manual_price) {
            manual_discount_amount = manual_price;
            row.custom_manual_discount_amount = flt(
                manual_price,
                precision("custom_manual_discount_amount", row)
            );
        }

        let discount_percentage = 0;
        let discount_amount = 0;
        let rate = manual_price;

        // Priority: percentage first, then amount, else no discount.
        if (manual_discount_percentage > 0) {
            discount_percentage = flt(
                manual_discount_percentage,
                precision("discount_percentage", row)
            );
            discount_amount = flt(
                manual_price * discount_percentage / 100,
                precision("discount_amount", row)
            );
            rate = manual_price - discount_amount;
        } else if (manual_discount_amount > 0) {
            discount_percentage = 0;
            discount_amount = flt(
                manual_discount_amount,
                precision("discount_amount", row)
            );
            rate = manual_price - discount_amount;
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

        // Detach any auto-applied pricing rule (e.g. from the Isnack Customer
        // Discount Rules pricing rules) so ERPNext does not re-apply or
        // reverse-calculate a compounded discount over the manual value.
        row.pricing_rules = "";
        row.is_free_item = 0;

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
};

// Recompute every manual line on the form, e.g. when the currency conversion
// rate changes and the base (company currency) fields need refreshing.
window.isnack_recalc_manual_lines = function (frm) {
    (frm.doc.items || []).forEach((row) => {
        isnack_apply_manual_line_discount(frm, row.doctype, row.name, false);
    });
};

// Register the manual pricing/discount grid handlers for the given child
// doctype (Sales Order Item / Quotation Item / Sales Invoice Item).
window.isnack_register_manual_line_handlers = function (item_doctype) {
    frappe.ui.form.on(item_doctype, {
        custom_manual_price_list_rate(frm, cdt, cdn) {
            isnack_apply_manual_line_discount(frm, cdt, cdn, true);
        },

        custom_manual_discount_percentage(frm, cdt, cdn) {
            // Entering a percentage clears the amount (mutual exclusivity).
            const row = locals[cdt] && locals[cdt][cdn];
            if (row) {
                row.custom_manual_discount_amount = 0;
            }
            isnack_apply_manual_line_discount(frm, cdt, cdn, true);
        },

        custom_manual_discount_amount(frm, cdt, cdn) {
            // Entering an amount clears the percentage (mutual exclusivity).
            const row = locals[cdt] && locals[cdt][cdn];
            if (row) {
                row.custom_manual_discount_percentage = 0;
            }
            isnack_apply_manual_line_discount(frm, cdt, cdn, true);
        },

        qty(frm, cdt, cdn) {
            isnack_apply_manual_line_discount(frm, cdt, cdn, false);
        },

        item_code(frm, cdt, cdn) {
            // Fallback init/re-assert once ERPNext's get_item_details call has
            // settled (the primary init happens in the price_list_rate event).
            isnack_after_ajax(() => {
                if (locals[cdt] && locals[cdt][cdn]) {
                    isnack_init_manual_price(frm, cdt, cdn);
                    isnack_apply_manual_line_discount(frm, cdt, cdn, false);
                }
            });
        },

        price_list_rate(frm, cdt, cdn) {
            // ERPNext triggers this after get_item_details / the item price
            // lookup has populated the standard price_list_rate. Initialise
            // the manual price list rate from it, then apply the manual flow.
            isnack_init_manual_price(frm, cdt, cdn);
            isnack_apply_manual_line_discount(frm, cdt, cdn, false);
        }
    });
};
