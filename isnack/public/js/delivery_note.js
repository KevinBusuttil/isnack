// Delivery Note line-level pallet quantity calculation.
//
// This mirrors the "Print Pallet Label" idea from the Operator Hub /
// Production Plan, but is intentionally kept separate: the logic here is
// specific to Delivery Note Item and is not shared with the pallet-label
// code in mes_ops.py / production_plan.js / operator_hub.js.
//
// Pallet Qty = row qty / conversion factor, where the conversion factor is
// the number of row-UOM units contained in one selected Pallet Type UOM.

frappe.ui.form.on("Delivery Note", {
    onload(frm) {
        isnack_dn_load_allowed_pallet_uoms(frm);
    },

    refresh(frm) {
        // Re-assert the Pallet Type filter (allowed UOMs may already be cached).
        isnack_dn_set_pallet_type_query(frm);
    },
});

frappe.ui.form.on("Delivery Note Item", {
    item_code(frm, cdt, cdn) {
        isnack_dn_calc_pallet_qty(frm, cdt, cdn);
    },

    qty(frm, cdt, cdn) {
        isnack_dn_calc_pallet_qty(frm, cdt, cdn);
    },

    uom(frm, cdt, cdn) {
        isnack_dn_calc_pallet_qty(frm, cdt, cdn);
    },

    custom_pallet_type(frm, cdt, cdn) {
        isnack_dn_calc_pallet_qty(frm, cdt, cdn);
    },

    custom_pallet_qty(frm, cdt, cdn) {
        // A direct edit of Pallet Qty in the grid is treated as a manual
        // override so the automatic calculation never clobbers it.
        const row = locals[cdt] && locals[cdt][cdn];
        if (row) {
            row.custom_pallet_qty_manual = 1;
            frm.refresh_field("items");
        }
    },

    custom_pallet_qty_manual(frm, cdt, cdn) {
        // Override switched off: fall back to the automatic calculation.
        const row = locals[cdt] && locals[cdt][cdn];
        if (row && !row.custom_pallet_qty_manual) {
            isnack_dn_calc_pallet_qty(frm, cdt, cdn);
        }
    },
});

// Load the allowed pallet UOMs from Factory Settings and cache them on the form.
function isnack_dn_load_allowed_pallet_uoms(frm) {
    frappe
        .call({
            method:
                "isnack.api.delivery_note_pallets.get_delivery_note_allowed_pallet_uoms",
        })
        .then((r) => {
            frm.__isnack_dn_allowed_pallet_uoms = (r && r.message) || [];
            isnack_dn_set_pallet_type_query(frm);
        });
}

// Restrict the Pallet Type Link field to the allowed pallet UOMs.
function isnack_dn_set_pallet_type_query(frm) {
    const allowed = frm.__isnack_dn_allowed_pallet_uoms || [];
    frm.set_query("custom_pallet_type", "items", () => ({
        filters: { name: ["in", allowed] },
    }));
}

// Recalculate Pallet Qty + Conversion Factor for a single Delivery Note Item.
function isnack_dn_calc_pallet_qty(frm, cdt, cdn) {
    const row = locals[cdt] && locals[cdt][cdn];
    if (!row) {
        return;
    }

    // Never overwrite a manually-entered Pallet Qty.
    if (row.custom_pallet_qty_manual) {
        return;
    }

    const item_code = row.item_code;
    const qty = flt(row.qty);
    const from_uom = row.uom;
    const pallet_type = row.custom_pallet_type;

    if (!item_code || !qty || !from_uom || !pallet_type) {
        row.custom_pallet_qty = null;
        row.custom_pallet_conversion_factor = null;
        frm.refresh_field("items");
        return;
    }

    frappe
        .call({
            method:
                "isnack.api.delivery_note_pallets.get_delivery_note_pallet_conversion",
            args: { item_code: item_code, from_uom: from_uom, to_uom: pallet_type },
        })
        .then((r) => {
            // The row may have been removed/changed while the call was in flight.
            const current = locals[cdt] && locals[cdt][cdn];
            if (!current || current.custom_pallet_qty_manual) {
                return;
            }

            const result = (r && r.message) || {};
            if (result.found && result.conversion_factor) {
                current.custom_pallet_conversion_factor = result.conversion_factor;
                current.custom_pallet_qty = flt(
                    flt(current.qty) / flt(result.conversion_factor),
                    precision("custom_pallet_qty", current)
                );
            } else {
                // No conversion configured: leave Pallet Qty blank.
                current.custom_pallet_conversion_factor = null;
                current.custom_pallet_qty = null;
            }
            frm.refresh_field("items");
            frm.dirty();
        });
}
