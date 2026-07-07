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
from frappe.utils import cint, flt


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
def suggest_pallets(doc) -> dict:
    """Build a pallet-manifest suggestion for a (possibly unsaved) Delivery Note.

    Called from the Delivery Note form with the current document as JSON; the
    client applies the returned allocations to the Pallets table. Pure
    suggestion — nothing is saved here.
    """
    doc = frappe.parse_json(doc)
    return _build_pallet_suggestion(doc.get("items") or [])


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

    # Soft cross-check: for items that appear in the manifest, compare the
    # allocated total against the Delivery Note quantity (per item + batch).
    allocated: dict = {}
    for allocation in allocations:
        key = (allocation.get("item_code"), allocation.get("batch_no") or "")
        allocated[key] = flt(allocated.get(key)) + flt(allocation.get("qty"))

    ordered: dict = {}
    for row in doc.get("items") or []:
        key = (row.get("item_code"), row.get("batch_no") or "")
        ordered[key] = flt(ordered.get(key)) + flt(row.get("qty"))

    problems = []
    for key, total in allocated.items():
        item_code, batch_no = key
        label = f"{item_code} ({batch_no})" if batch_no else item_code
        if key not in ordered:
            # Batch-agnostic fallback: manifest may omit or add the batch split.
            batchless_total = sum(
                qty for (item, _batch), qty in ordered.items() if item == item_code
            )
            if not batchless_total:
                problems.append(_("{0}: not on this Delivery Note").format(label))
            continue
        if abs(total - ordered[key]) > 0.001:
            problems.append(
                _("{0}: {1} allocated vs {2} on the Delivery Note").format(
                    label, flt(total, 4), flt(ordered[key], 4)
                )
            )

    if problems:
        frappe.msgprint(
            _("Pallet manifest quantities do not match the items: {0}").format(
                "; ".join(problems)
            ),
            indicator="orange",
            alert=True,
        )
