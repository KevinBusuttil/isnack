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
        isnack_dn_add_build_pallets_button(frm);
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

    custom_pallet_nos(frm, cdt, cdn) {
        // Assigning a Pallet No implies the type: fill an empty row Pallet
        // Type from the first referenced pallet in the Pallets table (which
        // also triggers the Pallet Qty calculation). An already-set type is
        // never overwritten; save-time validation warns on mismatches.
        const row = locals[cdt] && locals[cdt][cdn];
        if (!row || !row.custom_pallet_nos || row.custom_pallet_type) {
            return;
        }
        const first = (String(row.custom_pallet_nos).split(",")[0] || "")
            .split("-")[0]
            .trim();
        const pallet = (frm.doc.custom_pallets || []).find(
            (p) => cint(p.pallet_no) === cint(first)
        );
        if (pallet && pallet.pallet_type) {
            frappe.model.set_value(cdt, cdn, "custom_pallet_type", pallet.pallet_type);
        }
    },
});

frappe.ui.form.on("Pallet Detail", {
    // Auto-number new pallets so nobody types Pallet No by hand. The explicit
    // number (not the grid's positional No.) is what item rows reference, so
    // it must stay stable when other pallet rows are removed.
    custom_pallets_add(frm, cdt, cdn) {
        const row = locals[cdt] && locals[cdt][cdn];
        if (!row || row.pallet_no) {
            return;
        }
        let max = 0;
        (frm.doc.custom_pallets || []).forEach((p) => {
            if (p.name !== cdn && cint(p.pallet_no) > max) {
                max = cint(p.pallet_no);
            }
        });
        row.pallet_no = max + 1;
        frm.refresh_field("custom_pallets");
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
    // Same restriction for the Pallets table (field may not be migrated yet).
    if (frm.fields_dict.custom_pallets) {
        frm.set_query("pallet_type", "custom_pallets", () => ({
            filters: { name: ["in", allowed] },
        }));
    }
}

// "Build Pallets from Items": prefill the Pallets table + row assignments
// from the per-row Pallet Type/Qty calculation. Full pallets are allocated
// per row; fractional remainders are packed into shared (mixed) pallets of
// the same type. The result is a suggestion the user can regroup freely.
function isnack_dn_add_build_pallets_button(frm) {
    if (frm.doc.docstatus !== 0 || !frm.fields_dict.custom_pallets) {
        return;
    }

    frm.add_custom_button(__("Build Pallets from Items"), () => {
        const run = () => isnack_dn_build_pallets(frm);
        if ((frm.doc.custom_pallets || []).length) {
            frappe.confirm(
                __(
                    "This will replace the current Pallets table and the Pallet " +
                    "No(s) on all item rows. Continue?"
                ),
                run
            );
        } else {
            run();
        }
    });
}

function isnack_dn_build_pallets(frm) {
    frappe
        .call({
            method: "isnack.api.delivery_note_pallets.suggest_pallets",
            args: { doc: frm.doc },
            freeze: true,
            freeze_message: __("Building pallets..."),
        })
        .then((r) => {
            const result = (r && r.message) || {};
            const pallets = result.pallets || [];
            const assignments = result.assignments || {};

            frm.clear_table("custom_pallets");
            pallets.forEach((p) => {
                const row = frm.add_child("custom_pallets");
                row.pallet_no = p.pallet_no;
                row.pallet_type = p.pallet_type;
            });

            (frm.doc.items || []).forEach((item) => {
                item.custom_pallet_nos = assignments[item.name] || null;
            });

            frm.refresh_field("custom_pallets");
            frm.refresh_field("items");
            frm.dirty();

            if (pallets.length) {
                frappe.show_alert({
                    message: __("Built {0} pallet(s) from the item rows.", [
                        pallets.length,
                    ]),
                    indicator: "green",
                });
            } else {
                frappe.msgprint(
                    __(
                        "No pallets could be built. Set a Pallet Type (and a UOM " +
                        "conversion) on the item rows first."
                    )
                );
            }

            (result.unassigned || []).forEach((row) => {
                frappe.msgprint(
                    __("Row {0} ({1}) was not assigned to a pallet: {2}", [
                        row.idx,
                        row.item_code,
                        row.reason,
                    ])
                );
            });
        });
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
