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
# Physical pallets (custom_pallets table + per-row Pallet No(s) assignment)
#
# The Pallets child table on the Delivery Note lists each physical pallet
# (number + type). Item rows declare which pallets they are stacked on via
# the free-text `custom_pallet_nos` field ("1-3", "4,6"), so several
# items/batches can share one mixed pallet. The per-row Pallet Type/Qty
# fields above remain as a calculator; `suggest_pallets` turns them into a
# prefilled pallet table that the user can then regroup.
# ---------------------------------------------------------------------------

# Remainders differing from a whole pallet by less than this are snapped to
# the whole pallet, so 2.99/3.01 pallets both suggest 3 full pallets.
_FRACTION_SNAP = 0.02


def parse_pallet_nos(value) -> list[int]:
    """Parse a Pallet No(s) string like ``"1-3,6"`` into ``[1, 2, 3, 6]``.

    Raises ValueError on anything that does not parse to positive integers
    (callers turn this into a user-facing message with row context).
    """
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []

    numbers: set[int] = set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            raise ValueError(f"empty entry in {text!r}")
        if "-" in token:
            start_text, _, end_text = token.partition("-")
            start, end = int(start_text.strip()), int(end_text.strip())
            if start <= 0 or end < start:
                raise ValueError(f"invalid range {token!r}")
            numbers.update(range(start, end + 1))
        else:
            number = int(token)
            if number <= 0:
                raise ValueError(f"invalid pallet number {token!r}")
            numbers.add(number)
    return sorted(numbers)


def parse_pallet_nos_for_print(value) -> list[int]:
    """Lenient variant for Jinja print formats: bad input yields []."""
    try:
        return parse_pallet_nos(value)
    except (ValueError, TypeError):
        return []


def format_pallet_nos(numbers) -> str:
    """Format ``[1, 2, 3, 6]`` as ``"1-3,6"`` (inverse of parse_pallet_nos)."""
    numbers = sorted(set(int(n) for n in numbers or []))
    if not numbers:
        return ""

    parts: list[str] = []
    start = prev = numbers[0]
    for number in numbers[1:] + [None]:
        if number is not None and number == prev + 1:
            prev = number
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        if number is not None:
            start = prev = number
    return ",".join(parts)


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
    """Build a pallet table suggestion from item-row pallet quantities.

    Each row first receives its whole ("full") pallets; fractional remainders
    are then packed first-fit, in row order, into shared pallets of the same
    pallet type — which is exactly the mixed-pallet case the table exists for.
    Returns::

        {"pallets": [{"pallet_no": int, "pallet_type": str}, ...],
         "assignments": {row_key: "1-3,7", ...},
         "unassigned": [{"idx": int, "item_code": str, "reason": str}, ...]}
    """
    pallets: list[dict] = []
    assignments: dict = {}
    unassigned: list[dict] = []
    # Open shared pallets per pallet type: [pallet_no, used capacity 0..1]
    open_shared: dict[str, list[list]] = {}
    next_no = 1

    def _new_pallet(pallet_type: str) -> int:
        nonlocal next_no
        pallets.append({"pallet_no": next_no, "pallet_type": pallet_type})
        next_no += 1
        return next_no - 1

    for row in rows:
        row_key = row.get("name") or f"idx-{row.get('idx')}"
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
        full = int(pallet_qty + 1e-9)
        fraction = pallet_qty - full
        if fraction < _FRACTION_SNAP:
            fraction = 0.0
        elif fraction > 1 - _FRACTION_SNAP:
            full += 1
            fraction = 0.0

        numbers = [_new_pallet(pallet_type) for _ in range(full)]

        if fraction:
            shared = open_shared.setdefault(pallet_type, [])
            slot = next((s for s in shared if s[1] + fraction <= 1.0 + 1e-6), None)
            if slot is None:
                slot = [_new_pallet(pallet_type), 0.0]
                shared.append(slot)
            slot[1] += fraction
            numbers.append(slot[0])

        if numbers:
            assignments[row_key] = format_pallet_nos(numbers)

    return {"pallets": pallets, "assignments": assignments, "unassigned": unassigned}


@frappe.whitelist()
def suggest_pallets(doc) -> dict:
    """Build a pallet-table suggestion for a (possibly unsaved) Delivery Note.

    Called from the Delivery Note form with the current document as JSON; the
    client applies the returned pallets/assignments to the form. Pure
    suggestion — nothing is saved here.
    """
    doc = frappe.parse_json(doc)
    return _build_pallet_suggestion(doc.get("items") or [])


def validate_delivery_note_pallets(doc, method=None):
    """Delivery Note `validate` hook: keep the pallet table and row assignments coherent.

    Everything is optional — Delivery Notes without pallet data are untouched.
    Structural problems (bad numbers, references to missing pallets) block
    saving; softer inconsistencies only warn.
    """
    pallet_rows = doc.get("custom_pallets") or []
    item_rows = doc.get("items") or []
    has_assignments = any(row.get("custom_pallet_nos") for row in item_rows)
    if not pallet_rows and not has_assignments:
        return

    numbers: set[int] = set()
    for pallet in pallet_rows:
        number = cint(pallet.get("pallet_no"))
        if number <= 0:
            frappe.throw(
                _("Pallets table: row {0} needs a positive Pallet No.").format(
                    pallet.get("idx")
                )
            )
        if number in numbers:
            frappe.throw(
                _("Pallets table: Pallet No {0} is listed more than once.").format(number)
            )
        numbers.add(number)
        if not pallet.get("pallet_type"):
            frappe.throw(
                _("Pallets table: Pallet No {0} needs a Pallet Type.").format(number)
            )

    types_by_number = {
        cint(p.get("pallet_no")): p.get("pallet_type") for p in pallet_rows
    }
    referenced: set[int] = set()
    type_mismatch_rows: list = []

    for row in item_rows:
        raw = row.get("custom_pallet_nos")
        if not raw:
            continue
        try:
            row_numbers = parse_pallet_nos(raw)
        except ValueError:
            frappe.throw(
                _(
                    "Items row {0}: could not read Pallet No(s) {1}. Use numbers, "
                    "commas and ranges, e.g. \"1-3\" or \"4,6\"."
                ).format(row.get("idx"), frappe.bold(raw))
            )
        missing = [n for n in row_numbers if n not in numbers]
        if missing:
            frappe.throw(
                _(
                    "Items row {0}: Pallet No(s) {1} do not exist in the Pallets table."
                ).format(row.get("idx"), ", ".join(str(n) for n in missing))
            )
        referenced.update(row_numbers)

        row_type = row.get("custom_pallet_type")
        if row_type and any(types_by_number.get(n) != row_type for n in row_numbers):
            type_mismatch_rows.append(row.get("idx"))

    if pallet_rows and has_assignments:
        unreferenced = sorted(numbers - referenced)
        if unreferenced:
            frappe.msgprint(
                _("Pallet(s) {0} have no item rows assigned to them.").format(
                    format_pallet_nos(unreferenced)
                ),
                indicator="orange",
                alert=True,
            )
    if type_mismatch_rows:
        frappe.msgprint(
            _(
                "Items row(s) {0}: the row Pallet Type differs from the type of the "
                "assigned pallet(s)."
            ).format(", ".join(str(i) for i in type_mismatch_rows)),
            indicator="orange",
            alert=True,
        )
