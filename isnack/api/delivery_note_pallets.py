"""Delivery Note line-level pallet quantity calculation.

This mirrors the business idea behind the Operator Hub / Production Plan
"Print Pallet Label" feature, but is intentionally kept self-contained: the
conversion logic below is duplicated here on purpose so Delivery Note pallet
behaviour can evolve independently of the MES pallet-label code in
`isnack.api.mes_ops`. Do not refactor this into a shared utility.

Per Delivery Note Item row:
    Pallet Qty = row qty / conversion factor
where the conversion factor is the number of source-UOM units (the row UOM)
contained in one pallet UOM (the selected Pallet Type).
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate


def _allowed_pallet_uoms() -> list[str]:
    """Allowed pallet UOMs from Factory Settings.pallet_uom_options."""
    try:
        fs = frappe.get_cached_doc("Factory Settings")
    except Exception:
        return []
    rows = getattr(fs, "pallet_uom_options", None) or []
    return [row.uom for row in rows if getattr(row, "uom", None)]


def _item_uom_factor(item_code: str, uom: str) -> Optional[float]:
    """Conversion factor for `uom` from the Item's UOM Conversion Detail table.

    The factor is the number of stock-UOM units in one `uom`.
    """
    value = frappe.db.get_value(
        "UOM Conversion Detail",
        {"parent": item_code, "uom": uom},
        "conversion_factor",
    )
    return flt(value) if value else None


def _pallet_conversion_factor(item_code: str, from_uom: str, to_uom: str) -> Optional[float]:
    """Source-UOM units per one pallet UOM, or None when no conversion exists.

    Conversion priority (kept identical to the pallet-label code, but duplicated
    here so Delivery Note logic stays independent):
      1. Item UOM Conversion Detail (item-specific)
      2. global UOM Conversion Factor
      3. inverse global UOM Conversion Factor
    """
    if not item_code or not from_uom or not to_uom:
        return None

    if from_uom == to_uom:
        return 1.0

    try:
        # Priority 1: item-specific UOM Conversion Detail, expressed relative to
        # the item's stock UOM. Each factor is "stock units per that UOM", so
        # conversion = (stock units per pallet) / (stock units per source).
        stock_uom = frappe.get_cached_value("Item", item_code, "stock_uom")
        if stock_uom:
            from_factor = (
                1.0 if from_uom == stock_uom else _item_uom_factor(item_code, from_uom)
            )
            to_factor = (
                1.0 if to_uom == stock_uom else _item_uom_factor(item_code, to_uom)
            )
            if from_factor and to_factor:
                return to_factor / from_factor

        # Priority 2: global UOM Conversion Factor (from_uom -> to_uom).
        direct = frappe.db.get_value(
            "UOM Conversion Factor",
            {"from_uom": from_uom, "to_uom": to_uom},
            "value",
        )
        if direct:
            return flt(direct)

        # Priority 3: inverse global UOM Conversion Factor (to_uom -> from_uom).
        inverse = frappe.db.get_value(
            "UOM Conversion Factor",
            {"from_uom": to_uom, "to_uom": from_uom},
            "value",
        )
        if inverse:
            inverse = flt(inverse)
            if inverse:
                return 1.0 / inverse
    except Exception as e:
        frappe.log_error(
            title="Delivery Note Pallet Conversion Error",
            message=f"Error getting conversion factor for {item_code}: {str(e)}",
        )

    return None


def _apply_pallet_calculation(row) -> None:
    """Recalculate the pallet fields on a single Delivery Note Item row."""
    # A manual override is authoritative: never recompute the Pallet Qty.
    if row.get("custom_pallet_qty_manual"):
        return

    item_code = row.get("item_code")
    qty = flt(row.get("qty"))
    from_uom = row.get("uom")
    pallet_type = row.get("custom_pallet_type")

    if not (item_code and qty and from_uom and pallet_type):
        row.custom_pallet_qty = None
        row.custom_pallet_conversion_factor = None
        return

    factor = _pallet_conversion_factor(item_code, from_uom, pallet_type)
    if not factor:
        # No conversion configured: leave Pallet Qty blank rather than throwing,
        # so a Delivery Note is never blocked by missing UOM setup.
        row.custom_pallet_qty = None
        row.custom_pallet_conversion_factor = None
        return

    row.custom_pallet_conversion_factor = factor
    row.custom_pallet_qty = flt(qty / factor)


def calculate_delivery_note_pallets(doc, method=None):
    """Delivery Note `validate` hook: recalculate pallet quantities on every row.

    Runs server-side so Delivery Notes created via data import or the API get
    the same pallet calculation as those edited in the desk form.
    """
    for row in doc.get("items") or []:
        _apply_pallet_calculation(row)


@frappe.whitelist()
def get_delivery_note_allowed_pallet_uoms() -> list[str]:
    """Allowed pallet UOMs, used to filter the Delivery Note Item Pallet Type."""
    return _allowed_pallet_uoms()


@frappe.whitelist()
def get_delivery_note_pallet_conversion(item_code: str, from_uom: str, to_uom: str) -> dict:
    """Pallet conversion factor for a Delivery Note Item row (client-side calc)."""
    factor = _pallet_conversion_factor(item_code, from_uom, to_uom)
    if factor:
        return {"found": True, "conversion_factor": factor}
    return {"found": False, "conversion_factor": None}


# ---------------------------------------------------------------------------
# Pallet manifest (custom_pallets table)
#
# The Pallets child table on the Delivery Note is an allocation manifest:
# each row is an exact quantity of an item (optionally batch-specific) on one
# physical pallet. Rows sharing a Pallet No form one mixed pallet; an item
# split over several pallets simply has several rows. The per-row Pallet
# Type/Qty fields above remain a calculator; `suggest_pallets` turns them
# into a prefilled manifest that the user can then regroup or re-split with
# exact quantities.
# ---------------------------------------------------------------------------

# Remainders differing from a whole pallet by less than this are snapped to
# the whole pallet, so 2.99/3.01 pallets both suggest 3 full pallets.
_FRACTION_SNAP = 0.02


def _row_pallet_quantity(row: dict) -> Optional[float]:
    """Pallet quantity for a suggestion row, or None when not computable.

    A manual override is authoritative; otherwise qty / conversion factor,
    recomputing the factor when the row does not carry one yet.
    """
    qty = flt(row.get("qty"))
    if qty <= 0 or not row.get("custom_pallet_type"):
        return None

    if row.get("custom_pallet_qty_manual") and flt(row.get("custom_pallet_qty")) > 0:
        return flt(row.get("custom_pallet_qty"))

    factor = flt(row.get("custom_pallet_conversion_factor"))
    if not factor:
        factor = _pallet_conversion_factor(
            row.get("item_code"), row.get("uom"), row.get("custom_pallet_type")
        )
    if not factor:
        return None
    return qty / flt(factor)


def _build_pallet_suggestion(rows: list[dict]) -> dict:
    """Build a pallet manifest suggestion from item-row pallet quantities.

    Each row first fills its whole ("full") pallets — one allocation line per
    pallet, carrying qty / pallet-qty units each, so quantities always sum to
    the row exactly. Fractional remainders are then packed first-fit, in row
    order, into shared pallets of the same pallet type — the mixed-pallet
    case the manifest exists for. Returns::

        {"allocations": [{"pallet_no": int, "pallet_type": str,
                          "item_code": str, "batch_no": str | None,
                          "qty": float}, ...],
         "unassigned": [{"idx": int, "item_code": str, "reason": str}, ...]}
    """
    allocations: list[dict] = []
    unassigned: list[dict] = []
    # Open shared pallets per pallet type: [pallet_no, used capacity 0..1]
    open_shared: dict[str, list[list]] = {}
    counter = {"next_no": 1}

    def _new_pallet_no() -> int:
        counter["next_no"] += 1
        return counter["next_no"] - 1

    def _allocate(pallet_no, row, qty):
        allocations.append(
            {
                "pallet_no": pallet_no,
                "pallet_type": row.get("custom_pallet_type"),
                "item_code": row.get("item_code"),
                "batch_no": row.get("batch_no"),
                "qty": flt(qty, 4),
                "uom": row.get("uom"),
            }
        )

    for row in rows:
        if not row.get("custom_pallet_type") or flt(row.get("qty")) <= 0:
            continue

        pallet_qty = _row_pallet_quantity(row)
        if not pallet_qty:
            unassigned.append(
                {
                    "idx": row.get("idx"),
                    "item_code": row.get("item_code"),
                    "reason": "no UOM conversion to the selected Pallet Type",
                }
            )
            continue

        pallet_type = row.get("custom_pallet_type")
        qty = flt(row.get("qty"))
        full = int(pallet_qty + 1e-9)
        fraction = pallet_qty - full
        if fraction < _FRACTION_SNAP:
            fraction = 0.0
        elif fraction > 1 - _FRACTION_SNAP:
            full += 1
            fraction = 0.0

        # Units per full pallet, derived from the effective pallet quantity so
        # the allocation lines always sum back to the row quantity exactly
        # (including manual overrides, where qty/pallet is an even split).
        effective = full + fraction
        per_pallet = qty / effective if effective else 0

        for _unused in range(full):
            _allocate(_new_pallet_no(), row, per_pallet)

        if fraction:
            remainder_qty = qty - per_pallet * full
            shared = open_shared.setdefault(pallet_type, [])
            slot = next((s for s in shared if s[1] + fraction <= 1.0 + 1e-6), None)
            if slot is None:
                slot = [_new_pallet_no(), 0.0]
                shared.append(slot)
            slot[1] += fraction
            _allocate(slot[0], row, remainder_qty)

    allocations.sort(key=lambda a: a["pallet_no"])
    return {"allocations": allocations, "unassigned": unassigned}


@frappe.whitelist()
def get_bundle_batches(bundles) -> dict:
    """Batch numbers contained in the given Serial and Batch Bundles.

    Used by the Delivery Note form to filter the pallet manifest's Batch
    picker down to the batches actually selected on the item rows, which may
    live in a Serial and Batch Bundle rather than the row's batch_no field.
    Returns ``{bundle_name: [batch_no, ...]}``.
    """
    bundles = frappe.parse_json(bundles) if isinstance(bundles, str) else bundles
    if not bundles:
        return {}

    result: dict = {}
    for entry in frappe.get_all(
        "Serial and Batch Entry",
        filters={"parent": ["in", bundles], "batch_no": ["is", "set"]},
        fields=["parent", "batch_no"],
        parent_doctype="Serial and Batch Bundle",
    ):
        result.setdefault(entry.parent, [])
        if entry.batch_no not in result[entry.parent]:
            result[entry.parent].append(entry.batch_no)
    return result


def _is_batch_item(item_code: str) -> bool:
    """True when the item is batch-tracked (Item.has_batch_no)."""
    if not item_code:
        return False
    return bool(cint(frappe.get_cached_value("Item", item_code, "has_batch_no")))


def _missing_batch_rows(rows) -> list:
    """Palletised, batch-tracked rows that carry neither a batch nor a bundle.

    These block pallet building: the manifest is meant to be batch-exact, so
    batches must be selected on the item rows first. Non-batch-tracked items
    (e.g. packaging sold as items) are never blocked.
    """
    missing = []
    for row in rows:
        if not row.get("custom_pallet_type") or flt(row.get("qty")) <= 0:
            continue
        if not _is_batch_item(row.get("item_code")):
            continue
        if not row.get("batch_no") and not row.get("serial_and_batch_bundle"):
            missing.append(row)
    return missing


def _get_bundle_batch_quantities(bundles) -> dict:
    """Per-batch stock quantities of the given Serial and Batch Bundles.

    Returns ``{bundle_name: [(batch_no, abs_stock_qty), ...]}``. Outward
    bundles (deliveries) store negative quantities; absolute values are
    returned.
    """
    if not bundles:
        return {}

    result: dict = {}
    for entry in frappe.get_all(
        "Serial and Batch Entry",
        filters={"parent": ["in", list(bundles)], "batch_no": ["is", "set"]},
        fields=["parent", "batch_no", "qty"],
        parent_doctype="Serial and Batch Bundle",
    ):
        result.setdefault(entry.parent, []).append(
            (entry.batch_no, abs(flt(entry.qty)))
        )
    return result


def _expand_rows_by_batch(rows) -> list:
    """Split rows whose batches live in a Serial and Batch Bundle into one
    sub-row per batch, so the built manifest is batch-exact.

    Bundle entry quantities are stock-UOM; they are converted back to the
    row UOM via the row's conversion factor. A manual Pallet Qty override is
    scaled proportionally onto the sub-rows so its total is respected.
    """
    bundle_quantities = _get_bundle_batch_quantities(
        {row.get("serial_and_batch_bundle") for row in rows if row.get("serial_and_batch_bundle")}
    )

    expanded = []
    for row in rows:
        entries = bundle_quantities.get(row.get("serial_and_batch_bundle"))
        if not entries:
            expanded.append(row)
            continue
        conversion = flt(row.get("conversion_factor")) or 1.0
        row_qty = flt(row.get("qty"))
        for batch_no, stock_qty in entries:
            sub = dict(row)
            sub["batch_no"] = batch_no
            sub["qty"] = stock_qty / conversion
            if (
                row.get("custom_pallet_qty_manual")
                and flt(row.get("custom_pallet_qty")) > 0
                and row_qty
            ):
                sub["custom_pallet_qty"] = flt(row.get("custom_pallet_qty")) * (
                    (stock_qty / conversion) / row_qty
                )
            expanded.append(sub)
    return expanded


@frappe.whitelist()
def suggest_pallets(doc) -> dict:
    """Build a pallet-manifest suggestion for a (possibly unsaved) Delivery Note.

    Called from the Delivery Note form with the current document as JSON; the
    client applies the returned allocations to the Pallets table. Pure
    suggestion — nothing is saved here. Batch-tracked rows must carry their
    batch (or bundle) first, and bundle rows are expanded so every allocation
    line is batch-exact.
    """
    doc = frappe.parse_json(doc)
    rows = doc.get("items") or []

    missing = _missing_batch_rows(rows)
    if missing:
        frappe.throw(
            _(
                "Select batch numbers on the Delivery Note items before building "
                "pallets: {0}."
            ).format(
                ", ".join(
                    _("Row {0} ({1})").format(row.get("idx"), row.get("item_code"))
                    for row in missing
                )
            )
        )

    return _build_pallet_suggestion(_expand_rows_by_batch(rows))


def validate_delivery_note_pallets(doc, method=None):
    """Delivery Note `validate` hook: keep the pallet manifest coherent.

    Everything is optional — Delivery Notes without a manifest are untouched.
    Structural problems (bad numbers, conflicting pallet types, missing item
    or quantity) block saving; allocation totals that do not match the item
    rows only warn, so drafts can be saved mid-editing.
    """
    allocations = doc.get("custom_pallets") or []
    if not allocations:
        return

    types_by_no: dict[int, str] = {}
    for allocation in allocations:
        number = cint(allocation.get("pallet_no"))
        if number <= 0:
            frappe.throw(
                _("Pallets table: row {0} needs a positive Pallet No.").format(
                    allocation.get("idx")
                )
            )
        pallet_type = allocation.get("pallet_type")
        if not pallet_type:
            frappe.throw(
                _("Pallets table: row {0} (Pallet {1}) needs a Pallet Type.").format(
                    allocation.get("idx"), number
                )
            )
        if number in types_by_no and types_by_no[number] != pallet_type:
            frappe.throw(
                _(
                    "Pallets table: Pallet No {0} has conflicting Pallet Types "
                    "({1} and {2}). All rows of one pallet must agree."
                ).format(number, types_by_no[number], pallet_type)
            )
        types_by_no.setdefault(number, pallet_type)
        if not allocation.get("item_code"):
            frappe.throw(
                _("Pallets table: row {0} (Pallet {1}) needs an Item.").format(
                    allocation.get("idx"), number
                )
            )
        if flt(allocation.get("qty")) <= 0:
            frappe.throw(
                _("Pallets table: row {0} (Pallet {1}) needs a Qty above zero.").format(
                    allocation.get("idx"), number
                )
            )

    # A manifest may only exist once the batch-tracked items it covers have
    # their batches selected on the item rows (directly or via a Serial and
    # Batch Bundle) — same gate as the Build button, applied to manual entry.
    manifest_items = {a.get("item_code") for a in allocations}
    blockers = [
        row
        for row in doc.get("items") or []
        if row.get("item_code") in manifest_items
        and _is_batch_item(row.get("item_code"))
        and not row.get("batch_no")
        and not row.get("serial_and_batch_bundle")
    ]
    if blockers:
        frappe.throw(
            _(
                "Select batch numbers on the Delivery Note items before adding "
                "pallets: {0}."
            ).format(
                ", ".join(
                    _("Row {0} ({1})").format(row.get("idx"), row.get("item_code"))
                    for row in blockers
                )
            )
        )

    _validate_manifest_item_caps(doc, allocations)
    _validate_manifest_batches(doc, allocations)


def _dn_uom_maps(doc) -> tuple:
    """Stock-UOM conversion maps derived from the Delivery Note item rows.

    Returns ``(row_factor_by_item, row_factor_by_item_uom)``: the first row's
    conversion factor per item (fallback), and the factor per (item, uom)
    pair actually present on the rows.
    """
    row_factor_by_item: dict = {}
    row_factor_by_item_uom: dict = {}
    for row in doc.get("items") or []:
        item_code = row.get("item_code")
        factor = flt(row.get("conversion_factor")) or 1.0
        row_factor_by_item.setdefault(item_code, factor)
        if row.get("uom"):
            row_factor_by_item_uom.setdefault((item_code, row.get("uom")), factor)
    return row_factor_by_item, row_factor_by_item_uom


def _allocation_stock_factor(
    allocation, row_factor_by_item: dict, row_factor_by_item_uom: dict
) -> float:
    """Stock-UOM units per one manifest-row unit.

    Resolution: the (item, uom) factor from a matching Delivery Note row,
    then the item's own UOM conversion table (1.0 for the stock UOM itself),
    then the first row's factor for the item — so a manifest row without a
    UOM behaves exactly as before the field existed.
    """
    item_code = allocation.get("item_code")
    uom = allocation.get("uom")
    if uom:
        factor = row_factor_by_item_uom.get((item_code, uom))
        if factor:
            return factor
        if uom == frappe.get_cached_value("Item", item_code, "stock_uom"):
            return 1.0
        factor = _item_uom_factor(item_code, uom)
        if factor:
            return flt(factor)
    return row_factor_by_item.get(item_code, 1.0)


def _validate_manifest_item_caps(doc, allocations) -> None:
    """Hard cap: pallets must not carry more of an item than the Delivery Note ships.

    Quantities are compared in the stock UOM, aggregated over ALL Delivery
    Note rows of the item (the same item may appear on several lines, possibly
    in different UOMs). Exceeding the cap blocks saving; covering less only
    warns (a draft may be palletised halfway); manifest items missing from
    the Delivery Note entirely also warn.
    """
    row_factor_by_item, row_factor_by_item_uom = _dn_uom_maps(doc)

    ordered: dict = {}
    for row in doc.get("items") or []:
        item_code = row.get("item_code")
        factor = flt(row.get("conversion_factor")) or 1.0
        ordered[item_code] = flt(ordered.get(item_code)) + flt(row.get("qty")) * factor

    allocated: dict = {}
    for allocation in allocations:
        item_code = allocation.get("item_code")
        factor = _allocation_stock_factor(
            allocation, row_factor_by_item, row_factor_by_item_uom
        )
        allocated[item_code] = (
            flt(allocated.get(item_code)) + flt(allocation.get("qty")) * factor
        )

    warnings = []
    for item_code, total in allocated.items():
        if item_code not in ordered:
            warnings.append(_("{0}: not on this Delivery Note").format(item_code))
            continue
        if total > ordered[item_code] + 0.001:
            frappe.throw(
                _(
                    "Pallets table: {0} of {1} allocated across pallets, but the "
                    "Delivery Note only ships {2} (stock UOM)."
                ).format(flt(total, 4), item_code, flt(ordered[item_code], 4))
            )
        if total < ordered[item_code] - 0.001:
            warnings.append(
                _("{0}: {1} of {2} on pallets").format(
                    item_code, flt(total, 4), flt(ordered[item_code], 4)
                )
            )

    if warnings:
        frappe.msgprint(
            _("Pallet manifest does not fully match the items: {0}").format(
                "; ".join(warnings)
            ),
            indicator="orange",
            alert=True,
        )


def _get_available_batch_qty(batch_no: str, warehouse: str, item_code: str) -> float:
    """Current stock-UOM availability of a batch in a warehouse.

    Thin seam over erpnext's get_batch_qty (imported lazily so this module
    stays importable in plain unit tests), patched out in tests.
    """
    from erpnext.stock.doctype.batch.batch import get_batch_qty

    return flt(get_batch_qty(batch_no=batch_no, warehouse=warehouse, item_code=item_code))


def _validate_manifest_batches(doc, allocations) -> None:
    """Hard guardrails on manifest batches: no expired batch, no over-allocation.

    - A batch whose expiry_date lies before the posting date blocks saving.
    - Per (item, batch, warehouse), the allocated total (converted to the
      stock UOM via the item row's conversion factor) must not exceed the
      batch's current availability in that warehouse. The warehouse is the
      matching item row's, falling back to the document's source warehouse;
      when no warehouse can be determined the availability check is skipped.
    """
    posting_date = getdate(doc.get("posting_date") or nowdate())
    row_factor_by_item, row_factor_by_item_uom = _dn_uom_maps(doc)

    warehouse_by_item: dict = {}
    for row in doc.get("items") or []:
        if row.get("item_code") not in warehouse_by_item and row.get("warehouse"):
            warehouse_by_item[row.get("item_code")] = row.get("warehouse")

    totals: dict = {}
    for allocation in allocations:
        batch_no = allocation.get("batch_no")
        if not batch_no:
            continue
        item_code = allocation.get("item_code")
        warehouse = warehouse_by_item.get(item_code) or doc.get("set_warehouse")
        key = (item_code, batch_no, warehouse)
        stock_qty = flt(allocation.get("qty")) * _allocation_stock_factor(
            allocation, row_factor_by_item, row_factor_by_item_uom
        )
        totals[key] = flt(totals.get(key)) + stock_qty

    checked_expiry: set = set()
    for (item_code, batch_no, warehouse), stock_qty in totals.items():
        if batch_no not in checked_expiry:
            checked_expiry.add(batch_no)
            expiry = frappe.db.get_value("Batch", batch_no, "expiry_date")
            if expiry and getdate(expiry) < posting_date:
                frappe.throw(
                    _(
                        "Pallets table: Batch {0} expired on {1} and cannot be "
                        "put on a pallet."
                    ).format(batch_no, frappe.utils.formatdate(expiry))
                )

        if not warehouse:
            continue
        available = _get_available_batch_qty(batch_no, warehouse, item_code)
        if stock_qty > available + 0.001:
            frappe.throw(
                _(
                    "Pallets table: {0} of Batch {1} allocated, but only {2} "
                    "is available in {3}."
                ).format(flt(stock_qty, 4), batch_no, flt(available, 4), warehouse)
            )
