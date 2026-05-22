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
from frappe.utils import flt


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
