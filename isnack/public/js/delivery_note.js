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
    setup(frm) {
        isnack_dn_install_label_scanner(frm);
    },

    onload(frm) {
        isnack_dn_load_allowed_pallet_uoms(frm);
    },

    refresh(frm) {
        // Re-assert the Pallet Type filter (allowed UOMs may already be cached).
        isnack_dn_set_pallet_type_query(frm);
        isnack_dn_add_build_pallets_button(frm);
        isnack_dn_refresh_batch_cache(frm);
    },
});

frappe.ui.form.on("Delivery Note Item", {
    item_code(frm, cdt, cdn) {
        isnack_dn_calc_pallet_qty(frm, cdt, cdn);
        isnack_dn_refresh_batch_cache(frm);
    },

    batch_no(frm) {
        isnack_dn_refresh_batch_cache(frm);
    },

    serial_and_batch_bundle(frm) {
        isnack_dn_refresh_batch_cache(frm);
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

frappe.ui.form.on("Pallet Detail", {
    // Default a new manifest row to the highest pallet number in use. The
    // explicit number (not the grid's positional No.) is what groups rows
    // into physical pallets, so it must stay stable when rows are removed.
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

    pallet_no(frm, cdt, cdn) {
        // Rows of one pallet share its type: joining an existing pallet
        // number fills the Pallet Type from its other rows.
        const row = locals[cdt] && locals[cdt][cdn];
        if (!row || !row.pallet_no) {
            return;
        }
        const sibling = (frm.doc.custom_pallets || []).find(
            (p) =>
                p.name !== cdn &&
                cint(p.pallet_no) === cint(row.pallet_no) &&
                p.pallet_type
        );
        if (sibling && sibling.pallet_type !== row.pallet_type) {
            frappe.model.set_value(cdt, cdn, "pallet_type", sibling.pallet_type);
        }
    },

    item_code(frm, cdt, cdn) {
        // Default UOM from the matching item row, and Qty to the item's
        // still-unallocated Delivery Note quantity.
        const row = locals[cdt] && locals[cdt][cdn];
        if (!row || !row.item_code) {
            return;
        }
        const item_row = (frm.doc.items || []).find(
            (i) => i.item_code === row.item_code
        );
        if (item_row && item_row.uom && !row.uom) {
            frappe.model.set_value(cdt, cdn, "uom", item_row.uom);
        }
        if (flt(row.qty)) {
            return;
        }
        let ordered = 0;
        (frm.doc.items || []).forEach((item) => {
            if (item.item_code === row.item_code) {
                ordered += flt(item.qty);
            }
        });
        let allocated = 0;
        (frm.doc.custom_pallets || []).forEach((p) => {
            if (p.name !== cdn && p.item_code === row.item_code) {
                allocated += flt(p.qty);
            }
        });
        const remaining = ordered - allocated;
        if (remaining > 0) {
            frappe.model.set_value(cdt, cdn, "qty", remaining);
        }
    },
});

// ---------------------------------------------------------------------------
// Label scanning: teach the standard Scan Barcode field to read the
// ITEM|BATCH|QTY QR labels printed from the Operator Hub.
//
// The BarcodeScanner instance created by erpnext.TransactionController.setup
// is replaced with a subclass pointing at the isnack scan endpoint. While the
// feature is disabled in Factory Settings that endpoint proxies straight to
// erpnext.stock.utils.scan_barcode, so scanning behaves exactly as stock
// ERPNext; when a label is recognised the response carries isnack_* extras
// that drive the behaviours below (label-qty increments, a duplicate-label
// guard, and the restriction to items already on the Delivery Note).
// ---------------------------------------------------------------------------

const ISNACK_DN_SCAN_API = "isnack.api.delivery_note_scan.scan_delivery_note_code";

let isnack_dn_scanner_cls = null;

function isnack_dn_get_scanner_class() {
    if (isnack_dn_scanner_cls) {
        return isnack_dn_scanner_cls;
    }
    if (!window.erpnext || !erpnext.utils || !erpnext.utils.BarcodeScanner) {
        return null;
    }

    isnack_dn_scanner_cls = class IsnackDNLabelScanner extends erpnext.utils.BarcodeScanner {
        constructor(opts) {
            super(
                Object.assign(
                    {
                        scan_api: ISNACK_DN_SCAN_API,
                        play_success_sound: "submit",
                        play_fail_sound: "error",
                    },
                    opts
                )
            );
            // Raw payloads already applied on this form, to catch the same
            // physical label being scanned twice: every label is one carton
            // or pallet, so a repeat is almost always a double count.
            this.isnack_seen_labels = {};
        }

        process_scan() {
            this.isnack_last_input = (this.scan_barcode_field.value || "").trim();
            return super.process_scan();
        }

        update_table(data) {
            this.isnack_scan = null;
            if (!data || !data.isnack_label_scan) {
                return super.update_table(data);
            }
            this.isnack_scan = {
                qty: flt(data.isnack_scanned_qty),
                qty_mode: data.isnack_qty_mode || "Increment by Label Qty",
                stock_uom: data.isnack_stock_uom || null,
            };

            if (
                cint(data.isnack_restrict_to_existing_items) &&
                !(this.frm.doc[this.items_table_name] || []).some(
                    (r) => r.item_code === data.item_code
                )
            ) {
                this.show_alert(
                    __("Item {0} is not on this Delivery Note.", [data.item_code]),
                    "red"
                );
                this.clean_up();
                return Promise.reject();
            }

            const raw = this.isnack_last_input;
            const apply = () =>
                super.update_table(data).then((row) => {
                    if (raw) {
                        this.isnack_seen_labels[raw] =
                            (this.isnack_seen_labels[raw] || 0) + 1;
                    }
                    if (data.isnack_stock_warning) {
                        this.show_alert(data.isnack_stock_warning, "orange", 6);
                    }
                    return row;
                });

            if (raw && this.isnack_seen_labels[raw]) {
                return new Promise((resolve, reject) => {
                    frappe.confirm(
                        __(
                            "This exact label ({0}) was already scanned on this Delivery Note. Apply it again?",
                            [frappe.utils.escape_html(raw)]
                        ),
                        () => apply().then(resolve, reject),
                        () => {
                            this.clean_up();
                            reject();
                        }
                    );
                });
            }
            return apply();
        }

        set_item(row, item_code, barcode, batch_no, serial_no) {
            const scan = this.isnack_scan;
            if (!scan || scan.qty_mode === "Increment by 1") {
                return super.set_item(row, item_code, barcode, batch_no, serial_no);
            }

            return new Promise((resolve) => {
                const is_existing_row = !!row.item_code;

                // Label quantities are printed in the item's stock UOM;
                // convert when an existing row sells in another UOM.
                let qty = scan.qty;
                if (
                    qty &&
                    is_existing_row &&
                    scan.stock_uom &&
                    row[this.uom_field] &&
                    row[this.uom_field] !== scan.stock_uom &&
                    flt(row.conversion_factor)
                ) {
                    qty = flt(
                        qty / flt(row.conversion_factor),
                        precision(this.qty_field, row)
                    );
                }

                frappe.flags.trigger_from_barcode_scanner = true;
                const values = { item_code: item_code, use_serial_batch_fields: 1.0 };

                if (scan.qty_mode === "Assign Batch Only" && is_existing_row) {
                    // The batch lands via set_batch_no; the quantity of an
                    // already-present row is deliberately left alone.
                    frappe.model
                        .set_value(row.doctype, row.name, values)
                        .then(() => resolve(0));
                    return;
                }

                if (!qty) {
                    qty = 1;
                }
                values[this.qty_field] = flt(row[this.qty_field] || 0) + qty;
                frappe.model
                    .set_value(row.doctype, row.name, values)
                    .then(() => resolve(qty));
            });
        }

        show_scan_message(idx, is_existing_row, qty) {
            const scan = this.isnack_scan;
            if (scan && scan.qty_mode === "Assign Batch Only" && is_existing_row) {
                this.show_alert(__("Row #{0}: Batch assigned", [idx]), "green");
                return;
            }
            super.show_scan_message(idx, is_existing_row, qty);
        }
    };

    return isnack_dn_scanner_cls;
}

function isnack_dn_install_label_scanner(frm) {
    const cls = isnack_dn_get_scanner_class();
    // The controller's setup() has already created the stock scanner by the
    // time this handler runs; without a replacement the form simply keeps
    // stock scanning behaviour.
    if (cls && frm.cscript) {
        frm.cscript.barcode_scanner = new cls({ frm: frm });
    }
}

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
    // Same restriction for the Pallets table (field may not be migrated yet),
    // plus limit its Item picker to items actually on this Delivery Note and
    // its Batch picker to that item's batches — ideally only the batches
    // selected on the item rows (including Serial and Batch Bundle contents).
    if (frm.fields_dict.custom_pallets) {
        frm.set_query("pallet_type", "custom_pallets", () => ({
            filters: { name: ["in", allowed] },
        }));
        frm.set_query("item_code", "custom_pallets", () => ({
            filters: {
                name: ["in", (frm.doc.items || []).map((i) => i.item_code)],
            },
        }));
        frm.set_query("batch_no", "custom_pallets", (doc, cdt, cdn) => {
            const row = locals[cdt] && locals[cdt][cdn];
            const item_code = row && row.item_code;
            if (!item_code) {
                return {
                    filters: {
                        item: ["in", (frm.doc.items || []).map((i) => i.item_code)],
                    },
                };
            }
            const known =
                (frm.__isnack_dn_batches_by_item || {})[item_code] || [];
            if (known.length) {
                return { filters: { name: ["in", known] } };
            }
            // No batches picked on the rows yet: fall back to ERPNext's
            // standard batch search, which hides expired batches and only
            // offers stock available in the warehouse on the posting date.
            const item_row = (frm.doc.items || []).find(
                (i) => i.item_code === item_code
            );
            return {
                query: "erpnext.controllers.queries.get_batch_no",
                filters: {
                    item_code: item_code,
                    warehouse:
                        (item_row && item_row.warehouse) ||
                        frm.doc.set_warehouse,
                    posting_date: frm.doc.posting_date,
                },
            };
        });
    }
}

// Cache the batches selected on the item rows per item, so the pallet
// manifest's Batch picker can be narrowed to them. Batches may sit directly
// on the row (batch_no) or inside its Serial and Batch Bundle, whose entries
// are fetched server-side.
function isnack_dn_refresh_batch_cache(frm) {
    const by_item = {};
    const bundle_rows = [];
    (frm.doc.items || []).forEach((item) => {
        if (!item.item_code) {
            return;
        }
        by_item[item.item_code] = by_item[item.item_code] || [];
        if (item.batch_no && !by_item[item.item_code].includes(item.batch_no)) {
            by_item[item.item_code].push(item.batch_no);
        }
        if (item.serial_and_batch_bundle) {
            bundle_rows.push([item.item_code, item.serial_and_batch_bundle]);
        }
    });

    if (!bundle_rows.length) {
        frm.__isnack_dn_batches_by_item = by_item;
        return;
    }

    frappe
        .call({
            method: "isnack.api.delivery_note_pallets.get_bundle_batches",
            args: { bundles: bundle_rows.map((b) => b[1]) },
        })
        .then((r) => {
            const by_bundle = (r && r.message) || {};
            bundle_rows.forEach(([item_code, bundle]) => {
                (by_bundle[bundle] || []).forEach((batch) => {
                    if (!by_item[item_code].includes(batch)) {
                        by_item[item_code].push(batch);
                    }
                });
            });
            frm.__isnack_dn_batches_by_item = by_item;
        });
}

// "Build Pallets from Items": prefill the pallet manifest from the per-row
// Pallet Type/Qty calculation. Each row fills its full pallets (one manifest
// line per pallet with the exact quantity); fractional remainders are packed
// into shared (mixed) pallets of the same type. The result is a suggestion —
// the user can regroup rows or re-split quantities freely afterwards.
function isnack_dn_add_build_pallets_button(frm) {
    if (frm.doc.docstatus !== 0 || !frm.fields_dict.custom_pallets) {
        return;
    }

    frm.add_custom_button(__("Build Pallets from Items"), () => {
        const run = () => isnack_dn_build_pallets(frm);
        if ((frm.doc.custom_pallets || []).length) {
            frappe.confirm(
                __("This will replace the current Pallets table. Continue?"),
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
            const allocations = result.allocations || [];

            frm.clear_table("custom_pallets");
            const pallet_numbers = new Set();
            allocations.forEach((a) => {
                const row = frm.add_child("custom_pallets");
                row.pallet_no = a.pallet_no;
                row.pallet_type = a.pallet_type;
                row.item_code = a.item_code;
                row.batch_no = a.batch_no || null;
                row.qty = a.qty;
                row.uom = a.uom || null;
                pallet_numbers.add(a.pallet_no);
            });

            frm.refresh_field("custom_pallets");
            frm.dirty();

            if (allocations.length) {
                frappe.show_alert({
                    message: __("Built {0} pallet(s) from the item rows.", [
                        pallet_numbers.size,
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
